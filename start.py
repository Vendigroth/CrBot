#!/usr/bin/env python
#
# search.py
# Does the reddit search/post part of the bot.

import sys
import time
import signal
import sqlite3
import ConfigParser
import re
import urllib
import pyimgur
import praw
from praw.errors import ExceptionList, APIException, InvalidCaptcha, InvalidUser, RateLimitExceeded
import craigslist

def signal_handler(signal, frame):
    print 'Bye!'
    sys.exit(0)

##############################
# Globals
##############################
# Config file
config = ConfigParser.ConfigParser()
config.read("CraigslistBot.cfg")

# Reddit info
USERAGENT = ("Craigslist-Bot .02 by /u/Vendigroth")
USERNAME = config.get("Reddit", "username")
PASSWORD = config.get("Reddit", "password")
SUBREDDIT = config.get("Reddit", "subreddit")
SUBREDDIT = "coolcarsforsale+cars+autos"

# Imgur info
IMGUR_CID = config.get("Imgur", "clientId")
IMGUR_SECRET = config.get("Imgur", "clientSecret")

# Bot info
MAXPOSTS = config.get("Bot", "maxposts") # 100 is max.
WAIT = float(config.get("Bot", "sleeptime"))

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

sql = sqlite3.connect('sql.db')
print('Loaded SQL Database')
cur = sql.cursor()

# SQL
cur.execute('CREATE TABLE IF NOT EXISTS oldSubs(ID TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS clImage2imgurPic(clist TEXT , imgur TEXT)')
cur.execute('CREATE TABLE IF NOT EXISTS clLink2postData(clist TEXT, albumlink TEXT, commentlink TEXT)')

print('Loaded Completed table')

sql.commit()

crs = craigslist.CraigslistScraper()

##############################
# Scan a single sub (or a few with '+')
##############################
def scanSub(sub):

    #Too many loop prints. add proper logging?
    #print('Searching '+ sub + '.')

    subreddit = reddit.get_subreddit(sub)
    
    submissions = subreddit.search("site:\'craigslist\'",sort="new")
    
    for submission in submissions:
        processSubmission(submission)
    #for submission

def processSubmission(submission):
    
    pid = submission.id
    pageData = None
    commentText = None
    repost = False
    try:
        pauthor = submission.author.name
        cur.execute('SELECT * FROM oldSubs WHERE ID=?', [pid])
        if not cur.fetchone():    
            print "\nFound a new submission: (" + pid + ") " + submission.title
            print submission.url

            #For testing/ first load.
            #contVal = raw_input("Continue? (y/n)")
            #if contVal == '' or contVal.lower() == "y":
            #    print "Cont"
            #else:
            #    print "Skipping"
            #    cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
            #    sql.commit()
            #    return
            
            # If it's a direct image link... ignore it. 
            if "http://images.craigslist.org/" in submission.url:
                print "Direct image link. Skipping.\n"
                cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
                return

            # First check if saw that link before (x-post/repost/re-re-repost)
            cur.execute('SELECT * FROM clLink2postData WHERE clist=?', [submission.url])
            row = cur.fetchone()
            if not row:
                # No saved album/image. 
                # craigslist grab
                pageData = crs.scrapeUrl(submission.url)

                if not pageData:
                    print "Craigslits post is gone.\n"
                    cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
                    return
                
                replyLink = getImgurLink(submission.url, pageData.images, pageData.title)
                if not replyLink:
                    print "Messed up album\n"
                    return
                
                # Now have CL -> imgur pictures done. Deal with text.
                commentText = buildReply(replyLink, pageData)

            else:
                # Have an entry in db. Try to use it.
                replyLink = str(row[1])
                commentLink = row[2]
                # Already posted this one. re use old comment as a whole.
                if commentLink:
                    commentLink = str(commentLink)
                    print "Repost! using old text from permalink:\n" + commentLink
                    s = reddit.get_submission(commentLink)
                    oldComment = s.comments[0] # might want to handle out of range if comment can be deleted. 
                    commentText = "[x-post/repost:](" + commentLink + ")\n\n" + oldComment.body
                    repost = True
                else:
                # Have an image, but no text.
                # Still try to scrape, but no need to deal with images.
                    print "Just images"
                    pageData = crs.scrapeUrl(submission.url)
                    if not pageData:
                        # Post what we have.
                        print "Craigslits post is gone. Just posting the images.\n"
                        commentText = "**" + replyTitle +"**"  
                        commentText = commentText + "\n\n[Imgur Mirror Link](" + replyLink + ")" 
                        commentText = commentText + COMMENT_FOOTER
                    else:
                        commentText = buildReply(replyLink, pageData)

            print('Replying to ' + pid + ' by ' + pauthor + ':')
            print "======================================"
            print commentText
            print "======================================"
            
            comment = submission.add_comment(commentText)

            if comment and not repost:
                # Save permaling for a future repost. 
                print "Permalink " + comment.permalink
                print "Updating " + submission.url + " with " + comment.permalink
                cur.execute ('UPDATE clLink2postData SET commentlink=? WHERE clist=?', [comment.permalink, submission.url])
            
            # no errors? - dont look at it again.
            print "Inserting " + pid
            cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
            sql.commit()

    except RateLimitExceeded as err:
        print "Need to wait a bit.\n"
        return
    #except AttributeErrors as err:
    #    pauthor = '[DELETED]'
    except Exception as err:
        print('An error has occured:', err)

def getImgurLink(url, images, title):

    shortTitle = (title[:40] + '..') if len(title) > 40 else title
    
    # Imgur upload
    numImages = len(images)
    if numImages == 0:
        # No images. Need a way to handle that. Screenshot? not quite mobile fiiendly.
        print "No images. Not sure what to do.\n"
        return None
        
    if numImages > 0:
        print 'Have ' + str(numImages) + ' images'
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
                # Looks like craigslist doesn't let imgur to grab pics directly. meanies.
                # ok, download it, upload it, db it.
                print "Downloading: " + clImage
                urllib.urlretrieve(clImage, "temp.jpg")
                
                # Handle 0/1/many picture differences.
                try:
                    if numImages == 1:
                        print "Uploading 1"
                        imgrImage = im.upload_image(path="temp.jpg",title=shortTitle)#,description=pageData.body)
                        replyLink = imgrImage.link
                    else:
                        imgrImage = im.upload_image(path="temp.jpg")
                        imgrImages.append(imgrImage)
                except Exception as err:
                    print('Upload error: ', err)
                
                print "Uploaded to: " + imgrImage.link
                cur.execute('INSERT INTO clImage2imgurPic VALUES(?,?)', [clImage,imgrImage.id])
                
            else:
                imgrImage = im.get_image(str(row[0]))
                print "Re-using image: " + imgrImage.link
                imgrImages.append(imgrImage)
        
        if numImages == 1:
            # Just use the one we have
            replyLink = imgrImage.link             
        elif numImages > 1:
            #create an album
            print "Making an album"
            imgAlbum = im.create_album(title=shortTitle, images=imgrImages)
            print imgAlbum
            print "Album has :" + str(len(imgAlbum.images)) + "/" + str(numImages) + " images."
            if len(imgAlbum.images) != numImages:
                print "No good."
                return None
            replyLink = imgAlbum.link   
    cur.execute('INSERT INTO clLink2postData VALUES(?,?,?)', [url,replyLink,None])
    sql.commit()
    print "Saved link: " + replyLink

    # not sure if need for RES anymore. Used to chop so RES would follow.
    replyLink = re.sub('.jpg$', '', replyLink) 
    return replyLink

def buildReply(replyLink, pageData):
    replyTitle = None
    replyBody = None
    replyTable = None
    commentText = None
    
    replyTitle = pageData.title
    # Chop it at completely arbitrary 2k chars. 
    replyBody = (pageData.body[:2000] + '...') if len(pageData.body) > 2000 else pageData.body
    replyBody = ">" + replyBody
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
    commentText = commentText + "\n\n[Imgur Mirror Link](" + replyLink + ")"
    commentText = commentText + "\n\n" + replyBody
    commentText = commentText + "\n\n" + "&nbsp;"
    if replyTable:
        commentText = commentText + "\n\n" + replyTable
    commentText = commentText + COMMENT_FOOTER
    return commentText

##############################
# MAIN
##############################

def main():

    reddit.login(USERNAME, PASSWORD)
    
    if len(sys.argv) > 1:
        
        sub = str(sys.argv[1])
        print "trying a single submission: " + sub   
        submission = reddit.get_submission(submission_id=sub)
        print "Looking at submission: (" + submission.id + ") " + submission.title
        print submission.url
        print ""
        processSubmission(submission)
        sys.exit()

    print "Starting in search mode."
    print "Scanning : " + SUBREDDIT + " every " + str(WAIT/60) + " min."
    while True:
        try:
            #Scan sub submissions only. (for now) 
            scanSub(SUBREDDIT)
        except Exception as err:
           print('An error has occured:', err)
        #print('Running again in ' + str(WAIT) + ' seconds \n')
        sql.commit()
        time.sleep(WAIT)

##############################
# Go Go Go!
##############################

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()