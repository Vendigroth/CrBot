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
USERAGENT = ("Craigslist-Bot .01 by /u/Vendigroth")
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
cur.execute('CREATE TABLE IF NOT EXISTS clLink2postData(clist TEXT , title TEXT, link TEXT)')


print('Loaded Completed table')

sql.commit()

crs = craigslist.CraigslistScraper()

##############################
# Scan a single sub (or a few with '+')
##############################
def scanSub(sub):

    print('Searching '+ sub + '.')

    subreddit = reddit.get_subreddit(sub)
    
    submissions = subreddit.search("site:\'craigslist\'",sort="new")
    
    for submission in submissions:
        processSubmission(submission)
    #for submission

def processSubmission(submission):
    
    #print dir(submission)
    # should break this out to something ptretty, but need to decide on reply content
    # reply with album only/text in album? text in reply/pics only in album? decisions decisions.
    pid = submission.id
    pageData = None
    imgLink = None
    replyTitle = None
    replyBody = None
    try:
        pauthor = submission.author.name
        cur.execute('SELECT * FROM oldSubs WHERE ID=?', [pid])
        if not cur.fetchone():
            #cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
            
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
                
                # Imgur upload
                numImages = len(pageData.images)
                if numImages == 0:
                    # No images. Need a way to handle that. Screenshot? not quite mobile fiiendly.
                    print "No images. Not sure what to do.\n"
                    return

                if numImages > 0:
                    print 'Have ' + str(numImages) + ' images'
                    imgrImages = []
                    for clImage in pageData.images: 
                        # Clist seems to reuse image id's when post is re-posted
                        # so check in db incase we saw this one. (might be interesting if cl re-used id) 
                        # but this could avoid spamming imgur with same images

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
                                    imgrImage = im.upload_image(path="temp.jpg",title=pageData.title,description=pageData.body)
                                    imgLink = imgrImage.link
                                else:
                                    imgrImage = im.upload_image(path="temp.jpg")
                                    imgrImages.append(imgrImage)
                            except Exception as err:
                                print('Upload error: ', err)
                                return
    
                            print "Uploaded to: " + imgrImage.link
                            cur.execute('INSERT INTO clImage2imgurPic VALUES(?,?)', [clImage,imgrImage.id])
                            
                        else:
                            imgrImage = im.get_image(str(row[0]))
                            print "Re-using image: " + imgrImage.link
                            imgrImages.append(imgrImage)
                    
                    if numImages == 1:
                        # Just use the one we have
                        imgLink = imgrImage.link             
                    elif numImages > 1:
                        #create an album
                        print "Making an album"
                        shortTitle = (pageData.title[:40] + '..') if len(pageData.title) > 40 else pageData.title  
                        imgAlbum = im.create_album(title=shortTitle,description=pageData.body,images=imgrImages)
                        print imgAlbum

                        print "Album has :" + str(len(imgAlbum.images)) + "/" + str(numImages) + " images."
                        if len(imgAlbum.images) != numImages:
                            print "No good."
                            return
                        imgLink = imgAlbum.link   

                cur.execute('INSERT INTO clLink2postData VALUES(?,?,?)', [submission.url,pageData.title,imgLink])
                sql.commit()
                replyTitle = pageData.title
                replyBody = pageData.body
                print "Saved link: " + imgLink
            else:
                # Have an entry in db. Use it.
                replyTitle = str(row[1])
                imgLink = str(row[2])
                print "Re-using link: " + imgLink

            ##### make a reply
            imgLink = re.sub('.jpg$', '', imgLink) 
            commentText = "**" + replyTitle +"**\n\n" + "[Imgur Link](" + imgLink + ")^(^*Post ^body ^in ^description)" + COMMENT_FOOTER
            print('Replying to ' + pid + ' by ' + pauthor + ':')
            print "======================================"
            print commentText
            print "======================================"
            
            submission.add_comment(commentText)
            
            # no errors? - dont look at it again.
            cur.execute('INSERT INTO oldSubs VALUES(?)', [pid])
            sql.commit()
    except RateLimitExceeded as err:
        print "Need to wait a bit.\n"
        return
    #except AttributeErrors as err:
    #    pauthor = '[DELETED]'
    except Exception as err:
        print('An error has occured:', err)


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
    while True:
        try:
            #Scan sub submissions only. (for now) 
            scanSub(SUBREDDIT)
        except Exception as err:
           print('An error has occured:', err)
        print('Running again in ' + str(WAIT) + ' seconds \n')
        sql.commit()
        time.sleep(WAIT)

##############################
# Go Go Go!
##############################

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal_handler)
    main()