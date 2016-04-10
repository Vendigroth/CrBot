#!/usr/bin/python -u
#
# search.py
# Does the reddit search/post part of the bot.

import os
import sys
import time
import datetime
import signal
import sqlite3
import ConfigParser
import re
import requests
import pyimgur
import praw
from PIL import Image
from StringIO import StringIO
from praw.errors import ExceptionList, APIException, InvalidCaptcha, InvalidUser, RateLimitExceeded
import craigslist

##############################
# Return a pretty timestamp
##############################
def ts():
    return datetime.datetime.fromtimestamp(time.time()).strftime('%Y-%m-%d %H:%M:%S')+" "
##############################
# For catching SIGINT
##############################
def signal_handler(signal, frame):
    print ts(),'Bye!'
    sys.exit(0)

WD = "/home/pi/CrBot/"
#WD = ""
##############################
# Globals
##############################
# Config file
config = ConfigParser.ConfigParser()
config.read(WD+"craigslistBot.cfg")

# Reddit info
USERAGENT = ("Craigslist-Bot .02 by /u/Vendigroth")
USERNAME = config.get("Reddit", "username")
PASSWORD = config.get("Reddit", "password")
SUBREDDITS = config.get("Reddit", "subreddit")
if (',' in SUBREDDITS):
    SUBREDDITS = SUBREDDITS.split(",")

#SUBREDDITS = ["test"]

# Imgur info
IMGUR_CID = config.get("Imgur", "clientId")
IMGUR_SECRET = config.get("Imgur", "clientSecret")

# Push info If there is no section it will be ignored.
PUSHOVER = False
if config.has_section("Pushover"):
    PUSHOVER = True
    #PUSHOVER = False
    PUSH_TOKEN = config.get("Pushover", "token")
    PUSH_USER = config.get("Pushover", "user")

# Bot info
MAXPOSTS = config.get("Bot", "maxposts") # 100 is max.
WAIT = float(config.get("Bot", "sleeptime"))
ERROR_WAIT = 30

COMMENT_FOOTER = """
\n --- 
^| ^I'm ^a ^bot \
^| ^For ^bug ^reports ^or ^suggestions [^message ^/u/Vendigroth](http://www.reddit.com/message/compose/?to=Vendigroth) \
^|"""


##############################
# Set up
##############################

reddit = praw.Reddit(user_agent = USERAGENT)
im = pyimgur.Imgur(IMGUR_CID)

sql = sqlite3.connect(WD+'sql.db')
print ts(),'Loaded SQL Database'
cur = sql.cursor()

# SQL
cur.execute('CREATE TABLE IF NOT EXISTS oldSubs(ID TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS clImage2imgurPic(clist TEXT , imgur TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS clLink2postData(clist TEXT, albumlink TEXT, commentlink TEXT)')

print ts(),'Loaded Completed table'

sql.commit()

crs = craigslist.CraigslistScraper()

ERROR = False
ERROR_COUNT = 0
ERROR_RETRY_TIMES = 2

##############################
# Send a push notification
##############################
def send_push(message,**kwargs):
    if not PUSHOVER:
        return

    if not message:
        print ts(),"Nope. Need a message."
        return

    payload = {'token':PUSH_TOKEN,'user':PUSH_USER,'message':message}
    
    if kwargs is not None:
        for key, value in kwargs.iteritems():
            payload[key] = value

    url = 'https://api.pushover.net/1/messages.json'
    r = requests.post(url, data=payload)
    if r.status_code != 200:
        print ts(),"Push Error: ",r.status_code
        print r.text
    

##############################
# Check connection to reddit
##############################
def have_connection():
    try:
        response=requests.get('http://www.reddit.com/', timeout=7)
        return True
    except requests.ConnectionError as err: pass
    return False

##############################
# Scan a single sub (or a few with '+')
##############################
def scanSub(sub):
    print ts(),sub + ":"
    subreddit = reddit.get_subreddit(sub)
    submissions = subreddit.search("site:\'craigslist\'",sort="new")
    for submission in submissions:
        processSubmission(submission)

def processSubmission(submission):
    pid = submission.id
    pAuthor = "[DELETED]"
    try:
        if submission.author:
           pAuthor = submission.author.name
        
        cur.execute('SELECT * FROM oldSubs WHERE ID=?', [pid])
        if not cur.fetchone():   
            print ts(),"\nFound a new submission: (" + pid + ") " + submission.title
            print ts(),submission.url

            #For testing/ first load.
            TEST_MODE = False
            if TEST_MODE:
                contVal = raw_input("Continue? (y/n)")
                if contVal == '' or contVal.lower() == "y":
                    print "Cont"
                else:
                    print "Skipping"
                    cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
                    sql.commit()
                    return
            repost, title, commentText = getCommentTextFromUrl("oldSubs",pid,submission.url)

            #Verbose stuff
            #print "======================================"
            #print commentText
            #print "======================================"
            if commentText and title:
                print ts(),"Replying to ", pid, " by ", pAuthor
                comment = submission.add_comment(commentText)

                if comment:
                    # Save permalink for a future repost. 
                    print ts(),"Permalink ", comment.permalink
                    if not repost:
                        cur.execute ('UPDATE clLink2postData SET commentlink=? WHERE clist=?', [comment.permalink, submission.url])
                    
                    # Send a push notification with a link. (Curiosity)
                    send_push(submission.title,url="http://redd.it/"+pid,url_title=title)

                # no errors? - dont look at it again.
                print ts(),"Inserting ", pid
                cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
                sql.commit()
                ERROR = False


    except RateLimitExceeded as err:
        print ts(),"Need to wait a bit."
        return
    except Exception as err:
        print ts(),'An error has occured:', err
        if have_connection():
            send_push(err,title="Bot Error")

def getCommentTextFromUrl(table,pid,url):
    pageData = None
    repost = False
    commentText = None
    title = None
    # If it's a direct image link... ignore it. 
    if "http://images.craigslist.org/" in url:
        print ts(),"Direct image link. Skipping.\n"
        cur.execute('INSERT INTO '+table+' VALUES(?)', [pid])
        return (None, None, None)
    # First check if saw that link before (x-post/repost/re-re-repost)
    cur.execute('SELECT * FROM clLink2postData WHERE clist=?', [url])
    row = cur.fetchone()
    if not row:
        # No saved album/image. 
        # craigslist grab
        pageData = crs.scrapeUrl(url)

        if not pageData:
            print ts(),"Craigslits post is gone/invalid.\n"
            cur.execute('INSERT INTO '+table+' VALUES(?)', [pid])
            return (None, None, None)

        upload_tries = 0
        if len(pageData.images) != 0:
            replyLink = getImgurLink(url, pageData.images, pageData.title)
            while not replyLink and upload_tries < 2:
                upload_tries += 1
                print ts(),"Messed up album. Trying again"
                replyLink = getImgurLink(url, pageData.images, pageData.title)
            if not replyLink:
                print ts(),"Can't Upload\n"
                ERROR = True
                return (None, None, None)
        else:
            send_push("Got No images.")
            replyLink = None
        
        # Now have CL -> imgur pictures done. Deal with text.
        commentText = buildReply(replyLink, pageData)
        title = pageData.title

    else:
        # Have an entry in db. Try to use it.
        replyLink = str(row[1])
        commentLink = row[2]
        # Already posted this one. re use old comment as a whole.
        if commentLink:
            commentLink = str(commentLink)
            print ts(),"Repost! using old text from permalink:\n" + commentLink
            s = reddit.get_submission(commentLink)
            oldComment = s.comments[0] # might want to handle out of range if comment can be deleted. 
            commentText = "[x-post/repost:](" + commentLink + ")\n\n" + oldComment.body
            title = "Repost"
            repost = True
        else:
        # Have an image, but no text.
        # Still try to scrape, but no need to deal with images.
            print ts(),"Just images"
            try:
                pageData = crs.scrapeUrl(url)
            except Exception as err:
                print ts(),'An error has occured:', err
                if have_connection():
                    send_push(err,title="Bot Scrape Error")
            if not pageData:
                # Post what we have.
                print ts(),"Craigslits post is gone. Just posting the images.\n"
                commentText = commentText + "\n\n[Imgur Mirror Link](" + replyLink + ")" 
                commentText = commentText + COMMENT_FOOTER
            else:
                commentText = buildReply(replyLink, pageData)
                title = pageData.title
 
    return (repost, title, commentText)

def getImgurLink(url, images, title):

    shortTitle = (title[:40] + '..') if len(title) > 40 else title
    
    # Imgur upload
    numImages = len(images)
    if numImages == 0:
        # No images. Need a way to handle that. Screenshot? not quite mobile fiiendly.
        print ts(),"No images. Not sure what to do."
        return None
        
    if numImages > 0:
        print ts(),'Have ', numImages, ' images'
        imgrImages = []
        for clImage in images: 
            # Clist seems to reuse image id's when post is re-posted
            # so check in db incase we saw this one. (might be interesting if cl re-used id) 
            # but this could avoid spamming imgur with  
            cur.execute('SELECT imgur FROM clImage2imgurPic WHERE clist=?', [clImage])
            row = cur.fetchone()
            
            imgrImage = None
            if not row:
                # No saved image
                #Try to upload it directly
                try:
                    if numImages == 1:
                        imgrImage = im.upload_image(url=clImage,title=shortTitle)
                    else:
                        imgrImage = im.upload_image(url=clImage)

                    if not imgrImage:
                        #try downoading and uploading
                        print ts(),"Downloading: ", clImage
                        r = requests.get(clImage)
                        if r.status_code != 200:
                            print ts(), "Download Error: ", r.status_code
                            print ts(),r.text
                        i = Image.open(StringIO(r.content))
                        i.save(WD+"temp.jpg")
                        print ts(),"Downloaded"

                        if numImages == 1:
                            imgrImage = im.upload_image(path=WD+"temp.jpg",title=shortTitle)#,description=pageData.body)
                        else:
                            imgrImage = im.upload_image(path=WD+"temp.jpg")

                    imgrImages.append(imgrImage)

                except Exception as err:
                    print ts(),"Upload error: ", err
                    return None
                
                print ts(),"Uploaded to: ", imgrImage.link
                cur.execute('INSERT INTO clImage2imgurPic VALUES(?,?)', [clImage,imgrImage.id])
                
            else:
                imgrImage = im.get_image(str(row[0]))
                print ts(),"Re-using image: ", imgrImage.link
                imgrImages.append(imgrImage)
        
        if numImages == 1:
            # Just use the one we have
            replyLink = imgrImage.link             
        elif numImages > 1:
            #create an album
            print ts(),"Making an album"
            imgAlbum = im.create_album(title=shortTitle, images=imgrImages)
            print imgAlbum
            print ts(),"Album has :", len(imgAlbum.images), "/", numImages, " images."
            if len(imgAlbum.images) != numImages:
                print ts(),"No good."
                return None
            replyLink = imgAlbum.link   
    cur.execute('INSERT INTO clLink2postData VALUES(?,?,?)', [url,replyLink,None])
    sql.commit()
    print ts(),"Saved link: ", replyLink

    # not sure if need for RES anymore. Used to chop so RES would follow.
    replyLink = re.sub('.jpg$', '', replyLink) 
    return replyLink

def buildReply(replyLink, pageData):
    replyTitle = None
    replyBody = None
    replyTable = None
    commentText = None
    
    replyTitle = pageData.title
    # Chop it at completely arbitrary 7k chars. 
    replyBody = (pageData.body[:7000] + '...') if len(pageData.body) > 7000 else pageData.body
    # make a table out of attributes. 
    if pageData.attributes:
        replyTable = ''
        tabled = False
        for attr in pageData.attributes:
            replyTable = replyTable + attr + '|\n'
            if not tabled:
                replyTable = replyTable + ':-\n'
                tabled = True

    # make a reply from parts
    commentText = "**" + replyTitle +"**"
    if replyLink:
        commentText += "\n\n[Imgur Mirror Link](" + replyLink + ")"
    commentText += "\n\n"
    commentText = commentText.encode("utf-8")
    commentText += replyBody
    commentText += "\n\n".encode('utf8') + "&nbsp;".encode('utf8')
    if replyTable:
        commentText += "\n\n".encode('utf8')
        commentText += replyTable.encode('utf8')
    commentText += COMMENT_FOOTER.encode('utf8')
    return commentText

##############################
# MAIN
##############################

def main():
    #Check for internet/reddit connection first.
    while not have_connection():
        print ts(),"No internet connection available. Waiting ", WAIT
        time.sleep(WAIT)

    reddit.login(USERNAME, PASSWORD)
    
    if len(sys.argv) > 1:
        
        sub = str(sys.argv[1])
        print "trying a single submission: ", sub   
        submission = reddit.get_submission(submission_id=sub)
        print "Looking at submission: (", submission.id, ") ", submission.title
        print "URL: ", submission.url, "."
        print ""
        processSubmission(submission)
    else:
        send_push("Bot Started")
        print ts(),"Starting in search mode."
        print ts(),"Scanning : " + ",".join(SUBREDDITS) + " every ", WAIT/60, " min."
    while True:

        for subreddit in SUBREDDITS:
            try: 
                scanSub(subreddit)
            except Exception as err:
                print ts(),'An error has occured:', err
                if have_connection():
                    send_push(err,title="Error in " + subreddit)
                else:
                    while not have_connection():
                        print ts(),"No connection. Waiting until it's back"
                        time.sleep(WAIT)
            sql.commit()
        if not ERROR:
            time.sleep(WAIT)
            ERROR_COUNT = 0
        elif ERROR_COUNT < ERROR_RETRY_TIMES:
            print ts(),'Error! Trying again.'
            time.sleep(ERROR_WAIT)
        
##############################
# Go Go Go!
##############################

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()