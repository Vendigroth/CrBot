#CrBot
-------------------------------------

Bot that looks through a list of subreddits, grabs direct craigslist posts, copies them over to imgur, and replies with text of the post and the link to the album. Visited Posts, already uploaded images, and completed albums are stored in a sqlite3 database for re-use or in case of restart. 

Has an optional Pushover config to send push notifications with new posts or in case of an error.
