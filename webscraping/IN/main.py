from bs4 import BeautifulSoup
import requests
from lxml import etree

# Note: NO TBODIES
doc_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[2]/td[2]/font'
dob_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[7]/td[2]/font'
gender_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[8]/td[2]/font'
race_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[9]/td[2]/font'
facility_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[10]/td[2]/font'
# Earliest possible release date (may not be actual)
release_xpath = '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[11]/td[2]/font'

def scrape_page(url):
    html_record = requests.get(url)
    soup = BeautifulSoup(html_record.text, 'lxml')
    dom = etree.HTML(str(soup))

    def get_xpath_text(xpath):
        return ''.join(dom.xpath(xpath)[0].itertext())

    doc_number = get_xpath_text(doc_xpath)

    if doc_number == '':
        return False
    else:
        dob = get_xpath_text(dob_xpath)
        gender = get_xpath_text(gender_xpath)
        race = get_xpath_text(race_xpath)
        facility = get_xpath_text(facility_xpath)

        print(dob, gender, race, facility)
        return True

idoc_id = 1e5

while idoc_id < 2e5:
    print(idoc_id)
    scrape_page(f'https://www.in.gov/apps/indcorrection/ofs/ofs?previous_page=1&detail={int(idoc_id)}')
    idoc_id += 1