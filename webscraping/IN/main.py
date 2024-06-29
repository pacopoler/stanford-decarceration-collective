import requests
import time
import pandas as pd
from bs4 import BeautifulSoup
from lxml import etree

# To make working with the xpaths object easier (allows properties to be referenced with `.` instead of `[]`), stolen from stackoverflow
class dotdict(dict):
    """dot.notation access to dictionary attributes"""
    __getattr__ = dict.get
    __setattr__ = dict.__setitem__
    __delattr__ = dict.__delitem__

# Note: Remove tbodies when copying xpaths from inspect element
xpaths = dotdict({
    'doc': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[2]/td[2]/font',
    'dob': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[7]/td[2]/font',
    'gender': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[8]/td[2]/font',
    'race': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[9]/td[2]/font',
    'facility': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[10]/td[2]/font',
    # Earliest possible release date (may not be actual & does not reflect individual charges)
    'release': '/html/body/center[2]/table[1]/tr[1]/td[1]/table/tr[11]/td[2]/font',
    'charges': '/html/body/center[2]/table[1]/tr[3]/td[1]',
    # Xpaths for individual sentences (look within charges > table)
    'sentence_start': 'tr[2]/td[2]',
    'sentence_desc': 'tr[3]/td[2]',
    'conviction_type': 'tr[5]/td[2]',
    'citation_code': 'tr[6]/td[2]',
    'sentence_release': 'tr[9]/td[2]',
    'sentence_length': dotdict({
        'years': 'tr[4]/td[2]/table/tr/td[1]',
        'months': 'tr[4]/td[2]/table/tr/td[2]',
        'days': 'tr[4]/td[2]/table/tr/td[3]',
    })
})

scraped_df = pd.DataFrame({
    'doc_id': [],
    'dob': [],
    'gender': [],
    'race': [],
    'facility': [],
    'sentence_start': [],
    'sentence_desc': [],
    'conviction_type': [],
    'citation_code': [],
    'sentence_release': [],
    'sentence_length_years': [],
    'sentence_length_months': [],
    'sentence_length_days': []
})

# Apply preprocessing and save scraped_df as csv
def save_data(filename):
    scraped_df['sentence_start'] = pd.to_datetime(scraped_df['sentence_start'])
    scraped_df['sentence_release'] = pd.to_datetime(scraped_df['sentence_release'])
    scraped_df.to_csv(filename)

# just_checking argument is used to just check whether the offender record exists and skip further scraping
max_retries = 10
wait_time = 1
def scrape_page(idoc_id, just_checking=False, n_retries=1):
    try:
        html_record = requests.get(f'https://www.in.gov/apps/indcorrection/ofs/ofs?previous_page=1&detail={int(idoc_id)}')
        soup = BeautifulSoup(html_record.text, 'lxml')
        scrape_from_soup(soup, just_checking)
    except ConnectionError as e:
        if n_retries == 1:
            print(e, "\n Trying again...")

        if n_retries > max_retries:
            print("Failed after", max_retries, "retries, quitting")
            return
        else:
            print("Waiting", wait_time, "seconds before trying again")
            time.sleep(wait_time)
            scrape_page(idoc_id, just_checking, n_retries + 1)

def scrape_from_soup(soup, just_checking=False):
    dom = etree.HTML(str(soup))

    def innertext(elem):
        return ''.join(elem.itertext()).strip()

    def get_xpath_text(xpath):
        return innertext(dom.xpath(xpath)[0])

    doc_number = get_xpath_text(xpaths.doc).strip()
    record_exists = doc_number == ''

    if just_checking:
        return record_exists
    else:
        if record_exists:
            dob = get_xpath_text(xpaths.dob)
            gender = get_xpath_text(xpaths.gender)
            race = get_xpath_text(xpaths.race)
            facility = get_xpath_text(xpaths.facility)

            charges = dom.xpath(xpaths.charges)[0].findall("table")

            for charge in charges:
                sentence_start = innertext(charge.find(xpaths.sentence_start))
                sentence_desc = innertext(charge.find(xpaths.sentence_desc))
                conviction_type = innertext(charge.find(xpaths.conviction_type))
                citation_code = innertext(charge.find(xpaths.citation_code))
                sentence_release = innertext(charge.find(xpaths.sentence_release))
                # For some reason sentence_release contains an '\n' we want to remove
                sentence_release = sentence_release.replace('\n', '')

                sentence_length_years = innertext(charge.find(xpaths.sentence_length.years))
                sentence_length_months = innertext(charge.find(xpaths.sentence_length.months))
                sentence_length_days = innertext(charge.find(xpaths.sentence_length.days))

                scraped_df.loc[len(scraped_df.index)] = [
                    doc_number, dob, gender, race, facility, 
                    sentence_start, sentence_desc, conviction_type, citation_code, sentence_release,
                    sentence_length_years, sentence_length_months, sentence_length_days
                ]

                print(doc_number, dob, gender, race, facility, sentence_desc)
            
        return record_exists

def main():
    idoc_id = 1e5
    max_id = 2e5 + 1e4

    try:
        while idoc_id < max_id:
            scrape_page(idoc_id)
            idoc_id += 1
            
    # Save data if the script is force-quit
    except KeyboardInterrupt:
        pass
    finally:
        save_data('./scraped_data.csv')


def test():
    with open('test_rec.htm') as test_html:
        soup = BeautifulSoup(test_html, 'html.parser')
        scrape_from_soup(soup)

    save_data('./scraped_data_test.csv')

# Util to make sure we're not overwriting `Offender <x> exists` in the output from check_existence
def choose_end(last_existed):
    if last_existed:
        return ''
    else:
        return '\r'

# Check what records exist beyond start_id; used to find the maximum idoc_id for which there are offenders in the system
def check_existence(start_id):
    idoc_id = start_id
    last_existed = False

    while True:
        record_exists = scrape_page(idoc_id, just_checking=True)    

        if record_exists:
            print(f'Offender {int(idoc_id)} exists')
            last_existed = True
        else:
            print(f'Offender {int(idoc_id)} does not exist', end=choose_end(last_existed))
            last_existed = False
        
        idoc_id += 1

#test()  
#check_existence(2e5 + 1e4)
main()