#!/usr/bin/env python
#
# craigslist.py
# Grabs text and images from a posting


from BeautifulSoup import BeautifulSoup
from urlparse import urlparse
from HTMLParser import HTMLParser
from collections import namedtuple
import html2text
import requests
import re

class CraigslistScraper:
           
    def scrapeUrl(self, url):

        if ' ' in url:
            url = re.findall('http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', url)[0]
            print "\nFixing URL: " + url 

        if "about/best" in url:
        	print "URL:",url,"seems to be in 'best', ignoring."
        	return 0
        html = None
        try: 
        	html = requests.get(url)
        except Exception as err:
        	print('Error: ' + err)
        	return
        encoding = html.encoding
        #print encoding
        soup = BeautifulSoup(html.text)
        #print(soup.prettify())

        description = soup.head.find('meta', {'name':'description'})

        if (not description or
        	"This posting has expired." in description['content'] or 
        	"This posting has been flagged for removal." in description['content'] or 
        	"This posting has been deleted by its author." in description['content']):
            print "Broken"
            return 0

        #Get the title
        title = ""
        title = soup.find('h2', attrs={'class':'postingtitle'})
        if not title:
            print "There's no title"
            return 0
        title = title.text
        parser = HTMLParser()
        title = parser.unescape(title)
        # reddit doesn't like ';'
        title = re.sub(';', '', title)

        # Get and print contact info just in case. (Might be useful in the future)
        contact_ref = soup.find('a', "showcontact", href=True)
        if contact_ref:
            parsed_uri = urlparse(url)
            domain = '{uri.scheme}://{uri.netloc}'.format(uri=parsed_uri)
            contact_url = domain + contact_ref['href']
            contact = requests.get(contact_url).text
            contact = re.search('(\d{3}[-\.\s]??\d{3}[-\.\s]??\d{4}|\(\d{3}\)\s*\d{3}[-\.\s]??\d{4}|\d{3}[-\.\s]??\d{4})', contact)
            if contact:
              print "Removing Contact: " + contact.group(1)
           
        #Get the body
        body = ""
        body = soup.find(attrs={'id' : 'postingbody'}).renderContents()
        body = html2text.html2text(body.decode('utf8')).encode('utf-8')

        #print body
        # Remove contact info ref.
        body = re.sub('\[show\scontact\sinfo\]\([^)]*\)', '[REDACTED]', body)
        print body
        #print body
        # Reddit formatting tweaks
        body = re.sub("(  \n)+", "  \n", body)
        body = re.sub("(\n\n)+", "\n", body)
        body = '>'.join(('\n'+body.lstrip()).splitlines(True))
        body = re.sub("(\n)+", "\n\n", body)

        body = re.sub(';', ' ', body)
        
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
                temp_text =  span.text
                temp_text = parser.unescape(temp_text)
                if not 'more ads by this user' in temp_text:
                    attributes.append(temp_text)
                

        #Pack it up, and send it away
        PageData = namedtuple('PageData', 'title, body, images, attributes')
        pdt = PageData(title,body,images,attributes)
        return pdt
    
if __name__ == '__main__':
    

    url = "http://newyork.craigslist.org/brx/cto/5508185707.html"

    crs = CraigslistScraper()
    pdt = crs.scrapeUrl(url)

    print "====================="
    if pdt:
        print "Title:"
        print pdt.title
        print "Body:"
        print pdt.body
        print "\nHave: " + str(len(pdt.images)) + " images."
        for image in pdt.images:
            print image
        print ""
        for attr in pdt.attributes:
            print attr
    else:
        print "oops. post is gone"
