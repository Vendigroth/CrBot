#!/usr/bin/env python
#
# craigslist.py
# Grabs text and images from a posting


from urllib2 import urlopen, URLError
from BeautifulSoup import BeautifulSoup
from HTMLParser import HTMLParser
from collections import namedtuple
import html2text
import re

class CraigslistScraper:

    #def __init__(self):
           
    def scrapeUrl(self, url):

        html = None
        try:
            html = urlopen(url)
        except URLError as err:
            print('Error: ' + str(err.code ) + " " + str(err.reason))
            return

        soup = BeautifulSoup(html)
        #print(soup.prettify())
        
        description = soup.head.find('meta', {'name':'description'})['content']
        if "This posting has expired." in description or "This posting has been flagged for removal." in description or "This posting has been deleted by its author." in description:
            print "Broken: " + description
            return 0
        
        #Get the title
        title = ""
        title = soup.find('h2', attrs={'class':'postingtitle'}).text
        parser = HTMLParser()
        title = parser.unescape(title)
        
        #Get the body
        body = ""
        body = soup.find(attrs={'id' : 'postingbody'})
        body = html2text.html2text(str(body).decode("utf8"))
        body = re.sub('\[show contact info\].*\)', '[REDACTED]', body)
        body = body.rstrip('\n')
        
        #body = parser.unescape(body)
        
        #Get all the images
        images = []
        #If there are multiple grab all the images links.
        for link in soup.findAll('a'):
            linkText = link.get('href') or "";
            if 'images.craigslist' in linkText and str(linkText) not in images:
                images.append(str(linkText))

        #If theres one/none look for the title one.
        if not len(images):
            #print "Single image"
            for image in soup.findAll('img'):
                imageUrl = image.get('src') or "";
                if '600x450' in imageUrl:
                    images.append(str(imageUrl))


        
        #Get the attributes (top right box)
        attributes = []
        for attribute in soup.findAll('p', attrs={'class':'attrgroup'}):
            for span in attribute.findAll('span'):
                attributes.append(str(span.text))

        #Pack it up, and send it away
        PageData = namedtuple('PageData', 'title, body, images, attributes')
        pdt = PageData(title,body,images,attributes)
        return pdt
    
if __name__ == '__main__':
    
    print "====================="

    url = "http://london.craigslist.co.uk/cto/4782222165.html" 
    
    crs = CraigslistScraper()
    pdt = crs.scrapeUrl(url)

    if pdt:
        print pdt.title
        print ""
        print pdt.body
        print ""
        print "have: " + str(len(pdt.images)) + " images."
        for image in pdt.images:
            print image
        print ""
        for attr in pdt.attributes:
            print attr
    else:
        print "oops. post is gone"
