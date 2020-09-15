#!/usr/bin/env python
# coding: utf-8

# In[1]:


from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options  # for suppressing the browser head
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from ses_email import send_email
import re
import time
from datetime import datetime
import json
import atexit
import pandas as pd
import multiprocessing as mp
import os
import sys
from pathlib import Path

"""
Creates a webdriver to run the scraping in
"""
options = webdriver.ChromeOptions()
options.add_argument('--no-proxy-server')
options.add_argument('headless')
options.add_argument('log-level=3') # Suppresses error messages
# options.add_argument('--disable-gpu')



# Creates a Google Chrome webDriver object

# Path of chromedriver created below
# Give chromedriver exectuable permissions with chmod +x chromedriver
# Install chrome on the notebook using !curl https://intoli.com/install-google-chrome.sh | bash


#create the regular expression object which is used to search
#Looks for Mnemonic on the line above and then a new line and takes everything in between
arup_mnemonic_regex = re.compile(r'(?<=Mnemonic\n).+')
#Matches a string without whitespace then optional space then repeats. Has an extra space at the end
mayo_mnemonic_regex = re.compile(r'(?<=Test ID: )([^\s]+\s?)+')


arup_dict = {'main_site' : 'https://aruplab.com/testing',
             'info_block_id' : 'block-arup-content',
             'alpha_links_xpath' : '//div[@class = "toggle-container browse-menu"]',
             'result_table_xpath' : '/html/body/div[1]/div/main/div/div/div[3]/article/div/div/div/div', #Search result/alpha table
             'result_table_test_xpath' : '//div[@id="testName"]',
             'table_xpath' : '//table[@class = "ltd-table"]/tbody', # LOINC/analyte tables
             'ny_approval_xpath' : '//div[@class="field field--name-field-ny-approved-text field--type-string field--label-above"]/div[2]',
             'search_url' : 'https://ltd.aruplab.com/Search/SearchOrderables?search=',
             'search_separator' : '%20',
             'num_rows' : 8000,
             'analyte_columns' : {'test_code' : 0,
                                  'name' : 1,
                                  'loinc_code' : 2}}

mayo_dict = {'main_site' : 'https://www.mayocliniclabs.com/test-catalog/',
             'info_block_id' : 'pagebody',
             'alpha_links_xpath' : '//ul[@class = "active tab tab-panel"]',
             'result_table_xpath' : '//ul[@id= "tc-listing"]',
             'result_table_test_xpath' : '//li',
             'table_xpath' : '(//tbody[@class = "mobile-reponsive-body"])[2]',
             'ny_approval_xpath' : '//a[@name="ny_state_approval"]//following::div',
             'search_url' : 'https://www.mayocliniclabs.com/test-catalog/search.php?search=',
             'search_separator' : '+',
             'num_rows' : 11000,
             'analyte_columns' : {'test_code' : 0,
                                  'name' : 1,
                                  'loinc_code' : 2}}

labCorp_dict = {'main_site' : 'https://www.labcorp.com/test-menu/search',
                'info_block_id' : 'test-menu-left-col',
                'alpha_links_xpath' : '//ul[@class = "tm-refinement-menu"]',
                'result_table_xpath' : '//div[@class="tm-search-results-container"]',
                'result_table_test_xpath' : '//tr',
                'table_xpath' : '(//table[@id = "loinc-result"]/child::tbody)',
                'search_url' : 'https://www.labcorp.com/test-menu/search?query=',
                'search_separator' : '%20',
                'num_rows' : 16000,
                'analyte_columns' : {'test_code' : 3,
                                    'name' : 4,
                                     'uofm' : 5,
                                    'loinc_code' : 6}}



info_dict = {'arup' : arup_dict,
             'mayo' : mayo_dict,
             'labCorp' : labCorp_dict}


# # Input Variables

# In[2]:


#IS AUTOMATED NEEDS TO BE TRUE ON SERVER
is_automated = True #or False. Automated (can be run from cron with arguments) or manual (manually put arguments into code)
#Consider using something like if __name__ = __main__ to fix the problem with the script running when importing
bucket = 'hc1-prod-pentaho'



# Set defaults and then change them
abspath = Path(os.path.abspath(''))
path = abspath / 'chromedriver'
    #Create the global variables here. Search is automated (on server so different path but doesn't take args)
competitor = '' #labCorp, mayo, or arup
run_type = '' #Test or Full
is_search = True #True if searching for individual test
search_value = ''


if not is_automated:
    competitor = 'arup'
    run_type = 'Test'
    is_search = False
    search_value = '0070490'
    if len(sys.argv) > 1:
        print('CHANGE IS AUTOMATED VARIABLE TO TRUE')
if is_automated:
    abspath = Path(os.path.abspath(__file__)).parent #__file__ only works on server not in jupyter
    path = abspath / 'chromedriver'
    if len(sys.argv) > 1:
        competitor = sys.argv[1] #sys.argv[0] is automatically the file's name
        run_type = sys.argv[2]
        if sys.argv[3] == 'False':
            is_search = False
        search_value = sys.argv[4]


# # CSV Output Path

# In[3]:


#File name is kept the same and the files are overwritten every time
csv_output_path = abspath.parent / 'competitor_data_raw'
csv_output_name = ''
def create_output_path(status, letter_reached):
    global csv_output_name
    csv_output_name = competitor.upper() + '-CompetitorCompendiumScraped'
    global run_type
    if is_automated == False:
        prefix = os.fspath(csv_output_path) + '/' + competitor + status.upper() + run_type + datetime.now().strftime("%m-%d-%Y %H:%M:%S")
    elif is_automated ==True:
        prefix = os.fspath(csv_output_path) + '/' + csv_output_name
    suffix = '.csv'
    optional = ''
    if status != 'finished':
        optional += status
    if run_type == 'Test':
        optional += 'TEST'
    if status == 'unfinished':
        optional = 'UpTo' + letter_reached
    return prefix + optional + suffix 


# # Value Scraping Functions

# In[4]:


"""
Info block: Webelement that contains the majority of the relevant information
driver: Webdriver used to search
target_company: String, one of the competitors to search against
Returns: String, the test name
"""
def get_test_name(info_block, driver, target_company):
    if target_company == 'arup':
        return driver.find_element(By.XPATH, '//div[@class = "page-header"]/h1').text
        
#         return driver.find_element(By.XPATH, '/html/body/div[1]/div/main/div/div/div[2]/article/div[1]/div[1]/h1/p').text
    elif target_company =='mayo':
        mnemonic_block = driver.find_element(By.XPATH, '//h1')
        return re.sub(r'.+\n', '', mnemonic_block.text)
    elif target_company =='labCorp':
        return info_block.find_element(By.XPATH, '//h1').text

    
"""
Returns: String, test's abbreviation/mnemonic
"""
def get_mnemonic(info_block, driver, target_company):
    if target_company == 'arup':
        mnemonic_block = info_block.find_element(By.CLASS_NAME, 'field.field--name-field-mnemonic.field--type-string.field--label-above')
        return re.search(arup_mnemonic_regex, mnemonic_block.text).group(0)
    elif target_company == 'mayo':
        mnemonic_block = driver.find_element(By.XPATH, '//h1')
        return re.search(mayo_mnemonic_regex, mnemonic_block.text).group(0)[:-1] #slicing removes extra space

"""
Returns: String, the competitor's id code of the test
"""
def get_id_code(info_block, driver, target_company):
    if target_company == 'arup':
        return driver.find_element(By.XPATH, '//div[@class="field field--name-field-test-number field--type-string field--label-hidden field__item"]').text
    elif target_company == 'mayo':
        return re.findall(r'(?<=/)\d+$', driver.current_url)[0]
    elif target_company == 'labCorp':
        return info_block.find_element(By.XPATH, '//div[@class="test-number"]/descendant::a').get_attribute('data-tid')

"""
Returns: String, a list of five digit numbers separated by ---
"""
def get_cpt_code(info_block, driver, target_company):
    if target_company == 'arup':
        cpt_block = info_block.find_element(By.CLASS_NAME, 'cpt-codes-group')
        raw_text = cpt_block.find_element(By.CLASS_NAME, 'field__item').text
        
    elif target_company == 'mayo':
        codes_page_link = driver.find_element(By.XPATH, '//a[contains(@href, "Codes")]')
        driver.get(codes_page_link.get_attribute('href'))
        raw_text = driver.find_element(By.XPATH, '//a[@name="cpt_code_information"]//following::div').text
        
    elif target_company == 'labCorp':
        raw_text = info_block.find_element(By.XPATH, '//div[@class = "cpt-codes"]/span[2]').text
    code_list = re.findall(r'\d\d\d\d\d', raw_text)
    return '---'.join(code_list)
        
        
"""
Returns: String, list of cpt code descriptions separated by ---
"""
def get_cpt_code_description(info_block, driver, target_company):
    if target_company == 'mayo':
        cpt_code_element = driver.find_element(By.XPATH, '//a[@name="cpt_code_information"]//following::div')
        code_list = re.findall(r'.+', cpt_code_element.text)
        return '---'.join(code_list)


def get_analyte_names(info_block, driver, target_company):
    return get_analyte_info('name', driver, target_company)

           
def get_analyte_test_codes(info_block, driver, target_company):
    return get_analyte_info('test_code', driver, target_company)

    
def get_analyte_loinc_codes(info_block, driver, target_company):
    return get_analyte_info('loinc_code', driver, target_company)

"""
Returns: a list of values, one for each row in the analyte table
"""
def get_analyte_info(value, driver, target_company):
    info_list = []
    analyte_table = driver.find_element(By.XPATH, info_dict[target_company]['table_xpath']) 
    analyte_table_rows = analyte_table.find_elements(By.TAG_NAME, 'tr')
    for row in analyte_table_rows:
        columns = row.find_elements(By.TAG_NAME, 'td')
        column_index = info_dict[target_company]['analyte_columns'][value]
        
        if len(columns) > 0:
            #labCorp won't accept .text
            if target_company == 'labCorp':
                info_to_add = columns[column_index].get_attribute('innerHTML') # can probably be replaced with textContent
            else:
                info_to_add = columns[column_index].text

            if info_to_add == '':
                info_to_add = 'UNAVAILABLE'
            info_list.append(info_to_add)
    return info_list

"""
Returns: a JSON representation of the reflex tables for labcorp, organized by table
"""

def get_reflex_info(info_block, driver, target_company):
    if target_company == 'labCorp':
        reflex_dict = {}
        reflex_tables = driver.find_elements(By.XPATH, '//div[@id="loinc-map"]/descendant::table[@class="table table-bordered loinc-reflex stacktable large-only"]')
#         print('len reflex tables is', len(reflex_tables))
        for i, table in enumerate(reflex_tables):
#             print('table.text at top of for loop is', table.text)
#             print('table.text at top of for loop is', table.get_attribute('innerHTML'))
            temp_dict = table_to_dict(table, False)
#             print('temp_dict is', temp_dict)
            reflex_dict['Table ' + str(i)] = temp_dict
        if reflex_dict != {}:
            return json.dumps(reflex_dict)
        else:
            return 'UNAVAILABLE'
        

"""
Returns: string, concatenated list of alternate test names/aliases
""" 
def get_alternate_names(info_block, driver, target_company):
    names_concatenated = ''
    
    if target_company == 'arup':
        name_block = info_block.find_element(By.CLASS_NAME, 'field.field--name-field-cross-references.field--type-text-long.field--label-above')
        alternate_names = name_block.find_elements(By.TAG_NAME, 'li')
        for name in alternate_names:
            names_concatenated += (name.text + '---')
            
    elif target_company =='mayo':
        reporting_name = info_block.find_element(By.XPATH, '//a[@name="reporting_name"]//following::div').text
        print('reporting name is', reporting_name)
        names_concatenated+= (reporting_name + '---')
        try:
            aliases = info_block.find_element(By.XPATH, '//a[@name="aliases"]//following::div').text
            aliases = re.sub(r'\n', '---', aliases)
            names_concatenated += aliases
        except:
            pass
        
    elif target_company =='labCorp':
        alternate_names_block = info_block.find_element(By.XPATH, '//*[@id="test-menu-fields"]/div[1]/div[1]/h3')
        if  alternate_names_block.text == 'Synonyms':
            alternate_names_block = info_block.find_element(By.XPATH, '//*[@id="test-menu-fields"]/div[1]/div[2]/div/ul')
            alternate_names_list = alternate_names_block.find_elements(By.TAG_NAME, 'li')
            for name in alternate_names_list:
                names_concatenated += (name.text + '---')
                
    names_concatenated = re.sub(r'(---$)', '', names_concatenated)
    return names_concatenated

"""
Returns: string, the link to the test page
"""
def get_test_link(info_block, driver, target_company):
    return driver.current_url


"""
Returns: string, the specimen type (can be 'Varies' for Mayo)
"""
example_specimens = ['Serum', 'Plasma', 'Blood', 'Urine', 'CSF', 'Cerebrospinal Fluid']    
def get_specimen(info_block, driver, target_company):
    if target_company == 'arup':
        test_name = info_block.find_element(By.XPATH, '//div[@class = "page-header"]/h1').text
        specimen_type = re.findall(r'(?<=,\s)[^,]+$', test_name)
#         print('specimen type in arup before being checked is', specimen_type)
        if len(specimen_type) == 0 or not any(specimen in specimen_type[-1] for specimen in example_specimens):
            raw_text = info_block.find_element(By.XPATH, '//div[@class = "field field--name-field-specimen-collect field--type-text-long field--label-inline"]').text        
            specimen_type = re.search(r'(?<=Collect\s).+', raw_text).group(0)
        else:
            specimen_type = specimen_type[-1]
#         specimen_string = re.search(r'(?<=Collect\s).+', raw_text).group(0)
        return specimen_type

    elif target_company == 'mayo':
        specimen_page_link = info_block.find_element(By.XPATH, '//a[contains(@href, "test-catalog/Specimen")]')
#         print('got past specimen page link')
        driver.get(specimen_page_link.get_attribute('href'))
#         print('got to specimen page')
        specimen_type = driver.find_element(By.XPATH, '//a[@name = "specimen_type"]//following::div').text
#         print('got past getting specimen type')
        if specimen_type == 'Varies':
            specimen_required_text = driver.find_element(By.XPATH, '//a[@name = "specimen_required"]//following::div').text
            return '---'.join(re.findall(r'(?<=Specimen Type: ).+', specimen_required_text))
        else: 
            return specimen_type
    elif target_company == 'labCorp':
        return info_block.find_element(By.XPATH, '//div[@id="test-specimen"]/child::div/child::div[2]').text

"""
Returns: string of test methodology with \n removed
"""
def get_methodology(info_block, driver, target_company):
    if target_company == 'arup':
        methodology = info_block.find_element(By.XPATH, '//div[@class="field field--name-field-methodology field--type-text-long field--label-above"]/div[2]').text
    elif target_company == 'mayo':
        methodology = info_block.find_element(By.XPATH, '//a[@name = "method_name"]//following::div').text
    elif target_company == 'labCorp':
        test_details = info_block.find_element(By.XPATH, '//div[@id = "test-details"]')
        methodology = test_details.find_element(By.XPATH, '//h3[contains(text(), "Methodology")]/../../child::div[2]').text
    return re.sub(r'\n', ' ', methodology)

#Ensures no extra fields created bc of :
def decolon(string):
    return re.sub(':', ';', string)

"""
Returns: JSON of specimen info in form {specimen_type : {field_name: field_value}}
"""
def get_specimen_info(info_block, driver, target_company):
    specimen_dict = {}
    if target_company == 'arup':
        info_concatenated = ''
        specimen_type = get_specimen(info_block, driver, target_company)
#         print('specimen type in arup AFTER being checked is', specimen_type)
        first_child_div = info_block.find_element(By.XPATH, '//div[@class="specimen-required-container"]/child::div[1]')
        child_divs = info_block.find_elements(By.XPATH, '//div[@class="specimen-required-container"]/child::div[1]/following-sibling::div')
        child_divs.insert(0, first_child_div)
        for line in child_divs: #Get 'field name: field value'. Remove extra : so no accidental fields
            info_concatenated += (line.find_element(By.CLASS_NAME, 'field__label').text + ': ' + decolon(line.find_element(By.CLASS_NAME, 'field__item').text) + '\n')
        specimen_info_helper(specimen_dict, specimen_type, info_concatenated, driver)
        
    elif target_company == 'mayo':
        specimen_block = driver.find_element(By.XPATH, '//div[@id="test_catalog"]')
        specimen_type = driver.find_element(By.XPATH, '//a[@name = "specimen_type"]//following::div').text
        specimen_required_text = driver.find_element(By.XPATH, '//a[@name = "specimen_required"]//following::div').text
        try:
            specimen_required_text += ('\nMinimum Volume: ' + decolon(driver.find_element(By.XPATH, '//a[@name = "specimen_minimum_volume"]//following::div').text))
        except:
            pass
        if specimen_type == 'Varies':
            specimen_required_text = re.sub(r'\n\s', '---',specimen_required_text)
#             print('made it before list of chunks, spec text is', repr(specimen_required_text))
            list_of_chunks = re.split(r'---', specimen_required_text) # Text chunks
#             print('made it past list of chunks, which is', list_of_chunks)
            for chunk in list_of_chunks:
#                 print('got into chunk for loop, chunk is', repr(chunk))
                individual_specimen_type = re.findall(r'(?<=^Specimen Type: ).+|(?<=^ Specimen Type: ).+', chunk, flags = re.MULTILINE)
#                 print('individual_specimen_type is', individual_specimen_type)
                if len(individual_specimen_type) == 1:
                    specimen_info_helper(specimen_dict, individual_specimen_type[0], chunk, driver)
#                     print('specimen dict in loop after chunk is', specimen_dict)
                elif len(individual_specimen_type) > 1:
                    global parallel_bad_tests_dict
                    add_bad_test('extra specimen type', driver.current_url)
        else:
            print('got into else for specimen info')
#             print('dict before is', specimen_dict)
            specimen_info_helper(specimen_dict, specimen_type, specimen_required_text, driver)
#             print('dict after is', specimen_dict)
#         print('specimen_dict is', specimen_dict)
#         print('repr spec require text is', repr(specimen_required_text))

    elif target_company == 'labCorp':
        specimen_required_block = driver.find_element(By.XPATH, '//div[@id = "test-specimen"]')
        specimen_type = specimen_required_block.find_element(By.XPATH, '//h3[contains(text(), "Specimen")]/../../child::div[2]').text
#         print('specimen_type is', specimen_type)
        specimen_block = driver.find_elements(By.XPATH, '//div[@id="test-specimen"]//child::h3/../..')
#         print('specimen_bloc len is', len(specimen_block))
        info_concatenated = ''
        for child in specimen_block:
            cell_value = decolon(child.find_element(By.CLASS_NAME, 'current-value').text)
            info_concatenated +=(child.find_element(By.TAG_NAME, 'h3').text + ': ' + cell_value + '\n')
#             print('info_concatenated for labCorp is', info_concatenated)
#         print(repr(info_concatenated))
        specimen_info_helper(specimen_dict, specimen_type, info_concatenated, driver)
    return json.dumps(specimen_dict)
    
storage_instructions = ''
   
"""
Takes required text in the format '[header] : [value]' so there can only be one : per value
Returns: dict of {specimen_type : {field_name: field_value}}
"""
def specimen_info_helper(specimen_dict, specimen_type, specimen_required_text, driver):
    global parallel_bad_tests_dict #probably unecessary
    specimen_dict[specimen_type] = {}
    line_list = re.findall(r'^.+', specimen_required_text, flags = re.MULTILINE)
#     print('line list is', line_list)
    multiline_header = ''
    multiline_info = ''
    for line in line_list:
#         print('at the top of the loop header is:', multiline_header,'info is:', multiline_info)
#         print('line is', line)
        if re.search(r'^\s*(.+)(?=:)', line):
            if multiline_header != '':
#                     print('adding multiline_header,', multiline_header, 'multiline_info', multiline_info)
                    if multiline_header in specimen_dict[specimen_type]:
                        add_bad_test('multiple occurrences of header: ' + multiline_header, driver.current_url)
#                         parallel_bad_tests_dict = parallel_bad_tests_dict.append({'ERROR_REASON' : 'multiple occurences of header' + multiline_header, 'PAGE_LINK' : driver.current_url}, ignore_index=True)
                    specimen_dict[specimen_type][multiline_header] = multiline_info
                    multiline_info, multiline_header = '',re.findall(r'^\s*(.+?)(?=:)', line)[0]
            else:
                multiline_header = re.findall(r'^\s*(.+?)(?=:)', line)[0]
            if re.search(r'(?<=:\s).+', line):
                multiline_info += re.findall(r'(?<=:\s).+', line)[0]
        elif multiline_header != '':
            multiline_info += line
#             print('multiline_info after adding line is', multiline_info)
    if multiline_info != '':
#         print('ADDED MULTILINE INFO AT END. info is', multiline_info)
        specimen_dict[specimen_type][multiline_header] = multiline_info
    
    for key in ['Storage Instructions', 'Storage/Transport Temperature']:
        if key in specimen_dict[specimen_type]:
            global storage_instructions
            storage_instructions = specimen_dict[specimen_type][key]
    
    for key in ['Specimen Type', 'Specimen']:
        if key in specimen_dict[specimen_type]:
#             print('dict keys before are', specimen_dict[specimen_type].keys())
            del specimen_dict[specimen_type][key]
#             print('dict keys after are', specimen_dict[specimen_type].keys())
    
    return specimen_dict

"""
Returns: String, storage instructions which were created while getting specimen_info
"""
def get_storage_instructions(info_block, driver, target_company):
    global storage_instructions
    return storage_instructions
        

mayo_uofms = []

def get_mayo_uofm_list(driver):
    global mayo_uofms
    driver.get('https://www.mayocliniclabs.com/test-catalog/appendix/measurement.html')
    table = driver.find_element(By.XPATH, '//table[@class="table table-bordered table-striped"]/tbody')
    rows = table.find_elements(By.TAG_NAME, 'tr')
#     print('len rows is', len(rows))
    list_of_uofms = []
    for row in rows:
#         print('row is', row.text)
        cells = row.find_elements(By.TAG_NAME, 'td')
#         print('cells is', cells[0].text)
        list_of_uofms.append(cells[1].text)
        list_of_uofms.append(re.sub(r'\(s\)', '', cells[0].text))
    mayo_uofms = list_of_uofms

"""
Returns: list, the unit of measure matched to the appropriate analyte, or UNAVAILABLE
"""
#Unit of Measure
def get_uofm(info_block, driver, target_company):
    if target_company == 'arup':
        info_list = []
        modal_table = driver.find_element(By.XPATH, '//*[@id="itmp-modal-container"]/div[2]') #From a hidden modal
        rows = modal_table.find_elements(By.XPATH, '//*[@id="itmp-modal-container"]/div[2]/descendant::div[@class="field__item"]')
        for i, row in enumerate(rows):
            analyte_name = row.find_element(By.XPATH, '//*[@id="itmp-modal-container"]/div[2]/descendant::div[@class="field__item"][' + str(i + 1) + ']/div/div[@class="field field--name-field-description field--type-string field--label-hidden field__item"]').get_attribute('textContent')
            uofm = row.find_element(By.XPATH, '//*[@id="itmp-modal-container"]/div[2]/descendant::div[@class="field__item"][' + str(i + 1) + ']/div/div[@class="field field--name-field-unit-of-measure field--type-string field--label-hidden field__item"]').get_attribute('textContent')
            info_list.append((analyte_name.strip(), uofm.strip()))
        #             print('row.text is', repr(row.get_attribute('textContent')))
#             row_text = re.findall(r'(\S+\s?\S*)+', row.get_attribute('textContent'))
# #             print('row_text is', row_text)
#             info_list.append((row_text[1].strip(), row_text[4].strip()))

#             print('info_list is', info_list)
#             info_list.append(row.find_element(By.CLASS_NAME, 'field field--name-field-description field--type-string field--label-hidden field__item'), row.find_element(By.CLASS_NAME, 'field field--name-field-unit-of-measure field--type-string field--label-hidden field__item'))
        analytes_list = get_analyte_info('name', driver, target_company) #Could make this a global variable to avoid calling twice
        uofms = ['UNAVAILABLE' for i in range(len(analytes_list))]
        for analyte in info_list:
#             print('analyte tuple is', analyte)
            if analyte[0] in analytes_list:
                if analyte[1] =='':
                    analyte = (analyte[0],'UNAVAILABLE')
                uofms[analytes_list.index(analyte[0])] = analyte[1]
        return uofms
    elif target_company == 'mayo':
        ref_interval = driver.find_element(By.XPATH, '//a[@name = "reference_values"]//following::div').text
        uofms = ''
        for uofm in mayo_uofms:
            uofm_search = re.search('((?<=\s)' + uofm + '/\w+(/\w+)*)', ref_interval)
            if uofm_search:
                uofms+= uofm_search.group(0) + '---'

        return(uofms[:-3])
    elif target_company == 'labCorp':
        return get_analyte_info('uofm', driver, target_company)
    
"""
Returns: JSON of the reference intervals. If not in table format, creates dummy JSON of {'VALUES' : [text]}
"""
def get_reference_interval(info_block, driver, target_company):
    global parallel_bad_tests_dict
    if target_company == 'arup':
        table_exists = False
        reference_block = info_block.find_element(By.XPATH, '//div[@class = "field field--name-field-reference-interval field--type-text-long field--label-above"]/div[2]')
        try:
            table = reference_block.find_element(By.TAG_NAME, 'table')
            table_exists = True
            table_dict = table_to_dict(table, False)
            ref_intervals = json.dumps(table_dict)
            if 'Components' in table_dict:
                analytes_list = get_analyte_info('name', driver, target_company)
                ref_intervals = ['UNAVAILABLE' for i in range(len(analytes_list))]
                for analyte in table_dict['Components']:
                    if analyte in analytes_list:
                        ref_intervals[analytes_list.index(analyte)] = json.dumps({'VALUE' : table_dict['Reference Interval'][table_dict['Components'].index(analyte)]})
            return ref_intervals
        except:
            if table_exists:
                add_bad_test('table returned as text not JSON', driver.current_url)
                
#                 parallel_bad_tests_dict = parallel_bad_tests_dict.append({'ERROR_REASON' : 'table returned as text not JSON', 'PAGE_LINK' : driver.current_url}, ignore_index = True)
            if reference_block.text == '':
                return 'UNAVAILABLE'
            else:
                return json.dumps({'VALUE' : reference_block.text})
    elif target_company == 'mayo':
        clinical_page_link = driver.find_element(By.XPATH, '//a[contains(@href, "/test-catalog/Clinical+and+Interpretive")]')
        driver.get(clinical_page_link.get_attribute('href'))
        reference_block = driver.find_element(By.XPATH, '//a[@name = "reference_values"]//following::div')
        try:
            table = reference_block.find_element(By.TAG_NAME, 'table')
            table_dict = table_to_dict(table, False)
            ref_intervals = table_dict
        except:
            ref_intervals = {'VALUE' : reference_block.text}
        return json.dumps(ref_intervals)
        
"""
Takes a table webelement and turns it into a python dictionary
is_nested: if table_to_dict is being called on a table inside a table
"""
def table_to_dict(table, is_nested):
    if is_nested:
        print('GOT INTO NESTED TABLE TO DICT LOOP')
    global parallel_bad_tests_dict
    try:
        thead = table.find_element(By.TAG_NAME, 'thead')
        head_rows = thead.find_elements(By.TAG_NAME, 'tr')
        columns = head_rows[-1].find_elements(By.TAG_NAME, 'th')
#         print('len_columns is', len(columns), 'is_nested:', is_nested)
    except: # No head
#         print('got into except at top of table_to_dict')
        if competitor == 'mayo': #First row in tbody is header
            thead = table.find_element(By.TAG_NAME, 'tr')
            columns = thead.find_elements(By.TAG_NAME, 'td')
        else:
            columns = []
#     print('got past first except in table to dict')
    column_names = []
    if columns == []:
        first_row = table.find_element(By.TAG_NAME, 'tr')
        for i, cell in enumerate(first_row.find_elements(By.TAG_NAME, 'td')):
            column_names.append('Column ' + str(i))
    else:
        for column in columns:
            if column.text == '':
                column_names.append(column.get_attribute('textContent')) #text content catches text that .text doesnt
            else:
                column_names.append(column.text)
#     print('column_names is', column_names)
    column_dict = {column_names[i] : [] for i in range(len(column_names))}
    if 'Components' in column_names and not is_nested:
        tbody_row_1 = table.find_element(By.XPATH, '//div[@class = "field field--name-field-reference-interval field--type-text-long field--label-above"]/div[2]/table[1]/tbody[1]/tr[1]')

        tbody_rows = table.find_elements(By.XPATH, '//div[@class = "field field--name-field-reference-interval field--type-text-long field--label-above"]/div[2]/table[1]/tbody[1]/tr[1]/following-sibling::tr')
        tbody_rows.insert(0, tbody_row_1)
        
    else:
        tbody_rows = table.find_elements(By.TAG_NAME, 'tr')
#     print('NUMBER OF ROWS FOUND IS', len(tbody_rows))
    column_content = [[] for i in range(len(column_names))]
    for row in tbody_rows:
#         print('column_content while is_nested:', is_nested, ' is', column_content)
        for i, cell in enumerate(row.find_elements(By.TAG_NAME, 'td')):
            if i >= len(column_content):
#                 print('too many elements with tag td found and is_nested: ', is_nested)
                break
            try:
                cell.find_element(By.TAG_NAME, 'table')
                info = json.dumps(table_to_dict(cell.find_element(By.TAG_NAME, 'table'), True))
            except:
                info = cell.text
                if info == '':
                    info = cell.get_attribute('textContent')
            column_content[i].append(info)
#     print('column content at end is', column_content)
    table_dict = {value : column_list for value, column_list in zip(column_names, column_content)}
#     print('table dict is', table_dict)
    return table_dict
"""
Returns: String, whether or not the test has been NY state approved
"""
def get_ny_approval(info_block, driver, target_company):
    return info_block.find_element(By.XPATH, info_dict[target_company]['ny_approval_xpath']).text


# # Webdriver Setup

# In[5]:


webdriver_list = []

#Ensure the webdrivers quit. TRY TO USE A WITH STATEMENT WITH WEBDRIVERS QUIT AS THE __EXIT__ METHOD
def quit_webdrivers():
    for instance in webdriver_list:
        instance.quit()
    print('webdrivers quit')
    
atexit.register(quit_webdrivers)


# # Values to Scrape

# In[6]:


#this is the only way to make columns since alpha scraper creates the df based on these values
class ValuesToScrape:
    
    
    def __init__(self, value_list):
        self.values =[('TEST_NAME', get_test_name),
                        ('TEST_ID_CODE', get_id_code),
                        ('ALTERNATE_TEST_NAMES', get_alternate_names),
                        ('TEST_METHODOLOGY', get_methodology),
                        ('TEST_SPECIMEN', get_specimen),
                        ('TEST_SPECIMEN_INFORMATION', get_specimen_info),
                        ('TEST_CPT_CODE', get_cpt_code),
                        ('TEST_LINK', get_test_link),
                        ('ANALYTES', get_analyte_names),
                        ('ANALYTE_TEST_CODES', get_analyte_test_codes),
                        ('ANALYTE_LOINC_CODES', get_analyte_loinc_codes),
                        ('TEST_UNIT_OF_MEASURE', get_uofm)]
        for value, pos in value_list:
            self.values.insert(pos, value)
            
labCorp_columns = ValuesToScrape([(('TEST_REFLEX_INFO', get_reflex_info), -1),
                                  (('TEST_STORAGE_INSTRUCTIONS', get_storage_instructions), -1)])

arup_columns = ValuesToScrape([(('TEST_MNEMONIC', get_mnemonic), 1),
                               (('TEST_NY_APPROVAL', get_ny_approval), -1),
                               (('TEST_STORAGE_INSTRUCTIONS', get_storage_instructions), -1),
                               (('TEST_REFERENCE_INTERVAL', get_reference_interval), -1)])

#CPT code description needs to be after CPT code so its on the correct webpage
mayo_columns = ValuesToScrape([(('TEST_REFERENCE_INTERVAL', get_reference_interval), -1),
                                (('TEST_MNEMONIC', get_mnemonic), -1),
                               (('TEST_CPT_CODE_DESCRIPTION', get_cpt_code_description), 7),
                               (('TEST_NY_APPROVAL', get_ny_approval), 3)])


values_to_scrape = {'arup' : arup_columns.values,
                    'mayo' : mayo_columns.values,
                    'labCorp' : labCorp_columns.values}


# # Global Variables

# In[7]:



global_dataframe = pd.DataFrame(columns = ['TEST_NAME']) # Create a dummy dataframe that will be added to later
# global_dataframe = pd.DataFrame(columns = values_to_scrape[competitor][0])
parallel_bad_tests_dict = {'ERROR_REASON' : [], 'PAGE_LINK' : []}
main_bad_tests_dict = {'ERROR_REASON' : [], 'PAGE_LINK' : []}


#Add bad test to global parallel_bad_tests_dict that exists in parallel processess
def add_bad_test(reason, link):
#     print('GOT INTO ADD BAD TEST')
    global parallel_bad_tests_dict
    parallel_bad_tests_dict['ERROR_REASON'].append(reason)
    parallel_bad_tests_dict['PAGE_LINK'].append(link)


# # Page Scrapers

# In[8]:


"""
Scrapes individual test page and returns a dictionary of column:value pairs.
Also adds bad/incomplete tests to a global parallel_bad_tests_dict. Errors raised in individual scraper are suppressed
so broken test pages don't break the whole scraper.

link: string, a url
target_company: string, arup labCorp or mayo
"""
def scrape_individual_test_page(link, target_company):
    try:
        global parallel_bad_tests_dict
        global webdriver_list
        individual_driver = webdriver.Chrome(executable_path=path, options=options)
        webdriver_list.append(individual_driver)
        print('individual test page link is', link)
        individual_driver.get(link)
        info_block = individual_driver.find_element(By.ID, info_dict[target_company]['info_block_id'])                    
        #add_bad_test('TEST ERROR', individual_driver.current_url)
        #print('TAKE OUT THE ABOVE LINE IF NOT TESTING')

        finalDict = {}
        
        for value, function in values_to_scrape[target_company]:
#             test_start_time = time.time()
#             #for testing so errors aren't suppressed
#             try:
#                 finalDict[value] = function(info_block, driver, target_company)
#             except:
#                 quit_webdrivers()
#                 raise
            
            try:
                finalDict[value] = function(info_block, individual_driver, target_company)
                if type(finalDict[value]) == str:
                    finalDict[value] = re.sub(r'\n|\r', ' ', finalDict[value])
#                     raise NameError('TEST TO SEE IF ERROR WORKS')
                if finalDict[value] == '':
                    finalDict[value] = 'UNAVAILABLE'
            except NoSuchElementException: #This can be deleted, covered by general except but uglier output
                print('got into no such element for:', value)
                finalDict[value] = 'UNAVAILABLE'
#                 print('GOT TO ADD BAD TEST')
                add_bad_test('no such element: ' + value, individual_driver.current_url) #adds to bad_dict
            
            except KeyboardInterrupt:
                raise
            except Exception as inst:
                print('UNEXPECTED ERROR OCCURRED')
                print(inst)
                finalDict[value] = 'UNAVAILABLE'
                add_bad_test(str(inst) + ' for: ' + value, individual_driver.current_url)
#             print('finished', value, 'in ', time.time() - test_start_time, 'seconds') 
        individual_driver.quit()
        print(finalDict)
        pid = os.getpid()
        stream = os.popen('lsof -a -p '+ str(pid) + ' | wc -l')
        output = stream.read()
        print('files opened by pid ', pid, ': ', output.strip())

#         stream = os.popen('cat /proc/sys/fs/file-nr')
#         output = stream.read()
#         print('files opened: ', output.strip())
        return finalDict
    except KeyboardInterrupt:
        quit_webdrivers()
    except Exception as inst:
        try:
            print('current url is, ', individual_driver.current_url)
            add_bad_test(str(inst), individual_driver.current_url)
            individual_driver.quit()
        except Exception as inst2:
            print('INDIVIDUAL PAGE SCRAPER ERRORED WHEN CREATING INDIVIDUAL DRIVER. ERROR IS: ', str(inst2))
            add_bad_test('first error:' + str(inst) + ' second_error:' + str(inst2), str(link))
        print('error caught by scrape individual page at link', link)
        print('error is', inst)
        return {key : 'UNAVAILABLE' for key, f in values_to_scrape[target_company]}
#         raise
    

    

"""
Scrapes the page with all tests that start with "A" or "B", etc
link: string, a url
target_company: string, arup labCorp or mayo
"""
def scrape_alphabetized_page(link, target_company):
    try:
#         raise NameError("TEST ERROR FOR EMAIL")
        global webdriver_list
        global run_type
        alpha_driver = webdriver.Chrome(executable_path=path, options=options)
        webdriver_list.append(alpha_driver)
        testDict = {}
        for column_name, f in values_to_scrape[target_company]:
            testDict[column_name] = []

        
        print('link before checking if it has # is', link)
        #LabCorp's # page can't be navigated to with search=#, have to close some popups and then manually click the link
        if target_company == 'labCorp' and '#' in link:
            #For navigating through the pages of #
            try:
                alpha_driver.find_element(By.XPATH, '//button[@aria-label = "Click to close."]').click()
            except:
                pass
            if 'page' in link:
                page_num = re.findall(r'\d+', link)
                alpha_driver.find_element(By.XPATH, '//a[@aria-label = "Page ' + page_num[0] + '"]').click()
            else:
                alpha_driver.get(info_dict[target_company]['main_site'])
                
                try:
                    alpha_driver.find_element(By.XPATH, '//button[@id = "onetrust-accept-btn-handler"]').click()
                except:
                    pass
#                 second_driver.find_element(By.XPATH, '//a[@class ="onetrust-close-btn-handler onetrust-close-btn-ui banner-close-button onetrust-lg close-icon"]').click()
                alpha_driver.find_element(By.PARTIAL_LINK_TEXT, '#').click()
        else:
            alpha_driver.get(link)
        print('alpha_driver.get(link) is at', alpha_driver.current_url)
        #Wait until the first entry in the table is present to know the table is loaded
        WebDriverWait(alpha_driver, 2).until(
                                EC.presence_of_element_located((By.XPATH, info_dict[target_company]['result_table_test_xpath']))
                            )
        results_list = alpha_driver.find_element(By.XPATH, info_dict[target_company]['result_table_xpath'])
        #CHANGE THIS SO ITS JUST FIRST TEST/a
        if target_company == 'arup': #Only get the name link, not links in description
            results = results_list.find_elements(By.XPATH, '//div[@id="testName"]/a')
        else:
            results = results_list.find_elements(By.TAG_NAME, 'a')
        #Shorten the results list for testing
        if run_type == 'Test':
#             print('TEST REDUCED SLICING HAS BEEN COMMENTED OUT')
            results = results[:3]
        for result in results:
            individual_test_link = result.get_attribute("href")
            print('individual test link in scrape alpha page is', individual_test_link)
            individual_dict = scrape_individual_test_page(individual_test_link, target_company)
            if individual_dict['TEST_NAME'] != 'UNAVAILABLE':
                for key in individual_dict.keys():
                    if individual_dict['ANALYTES'] == 'UNAVAILABLE':
                        num_iters = 1
                    else:
                        num_iters = len(individual_dict['ANALYTES'])
                    for i in range(num_iters):
                        if type(individual_dict[key]) == str:
                            testDict[key].append(individual_dict[key])
                        elif type(individual_dict[key]) == list:
                            testDict[key].append(individual_dict[key][i])

        alpha_page_frame = pd.DataFrame.from_dict(testDict)
        alpha_driver.quit()
        return alpha_page_frame
    except NoSuchElementException: #non-fatal error, should stay suppressed
        alpha_page_frame = pd.DataFrame.from_dict(testDict)
        
        return alpha_page_frame
    except Exception as inst:
        send_error_email(inst, link)
        #ADD BAD TEST TO PARALLEL TEST
        quit_webdrivers()
        print('error caught by scrape alpha page: ', inst)
        raise

#Called every time a result is ready from the parallel processess
def callback(info_tuple):
    print('got into callback')
    global main_bad_tests_dict
    global global_dataframe
    temp_df = pd.concat(info_tuple[0], ignore_index = True)
    global_dataframe = pd.concat([global_dataframe, temp_df], ignore_index = True)
    for key in info_tuple[1]:
        main_bad_tests_dict[key] +=info_tuple[1][key]
    print('got into end of callback')
        
        
        
"""
Scrapes the main page of the site for links to the alphabetized pages and then
creates assigns each of those links to a worker process that returns a bad_dict and a df
which is then assigned to the global_dataframe variable.
Creates a webdriver to be used in scrape main page
"""
def scrape_main_page(target_company, driver):
    try:
        global main_bad_tests_dict
        global global_dataframe
        global run_type
        alpha_page_frames = []
        print(driver.current_url)

        #Get the links to each alphabetized page of tests
        alphabetized_pages_link = WebDriverWait(driver, 1).until(
                                EC.presence_of_element_located((By.XPATH, info_dict[target_company]['alpha_links_xpath']))
                            )
        list_of_links = alphabetized_pages_link.find_elements(By.TAG_NAME, 'a')
        if run_type == 'Test':
            list_of_links = list_of_links[:6]
        num_p = mp.cpu_count() #Num processess = num cpus
        if __name__ == '__main__':
            with mp.Pool(num_p) as pool:
                results = [pool.apply_async(scrape_alpha_page_loop, (link.get_attribute('href'), target_company,), callback = callback) for link in list_of_links]
                pool.close()
                pool.join()

        final_frame = global_dataframe
        quit_webdrivers()
        return final_frame
    except Exception as inst:
        global start_time
        main_bad_tests_dict['ERROR_REASON'].append(str(inst) + 'IN SCRAPE MAIN PAGE')
        main_bad_tests_dict['PAGE_LINK'].append(driver.current_url)
        
        quit_webdrivers()
        create_final_output_files(global_dataframe, 'unfinished')
        print('error caught by scrape main page: ', inst)
        print('time elapsed is', str((time.time()-start_time)))
        raise
        
def scrape_alpha_page_loop(link, target_company):
    global parallel_bad_tests_dict
    print(f'parallel_bad_tests_dict at START of alpha page loop is {parallel_bad_tests_dict}')
    global run_type
    time.sleep(5) #Ensured that this code wasn't skipped over in results but may not be necessary now
    alpha_page_frames = []
    bad_dict = {'ERROR_REASON' : [], 'PAGE_LINK' : []}
    print('NOW SCRAPING PAGES AT LINK', link)

    alpha_page_frames.append(scrape_alphabetized_page(link, target_company))
    #LabCorp has multiple pages per letter. Try each subpage until a blank one is hit
    if target_company == 'labCorp':
        print('got into top of labCorp multipage loop')
        scrapped_last_page = False
        j = 2
        #when run_type == 'Test' only looks through a few of the A2, A3, etc. pages
        i = 0
        while not scrapped_last_page and i < 3:
            curr_dataframe = scrape_alphabetized_page(link + "&page=" + str(j), target_company)
            print("is curr_dataframe empty?", curr_dataframe.empty)
            if curr_dataframe.empty:
                scrapped_last_page = True
            else:
                alpha_page_frames.append(curr_dataframe)
                print('appended', link + "&page=" + str(j), 'to dataframe')
                j += 1
            if run_type == 'Test':
                i += 1
    print(f'bad tests_dict in alpha page loop for {link} is', parallel_bad_tests_dict)
    for key in parallel_bad_tests_dict:
        bad_dict[key] += parallel_bad_tests_dict[key]
#     print('bad dict in alpha loop is', bad_dict)
    return (alpha_page_frames, bad_dict)
#     bad_dict = parallel_bad_tests_dict
#     print('alpha page frames at end of process:', mp.current_process().name, 'is', alpha_page_frames)


# In[9]:


"""
is_search: boolean, True or False
target_company: string, 'arup', 'mayo', or 'labCorp'
search_value: string, the value to be searched using the company's search function
returns: final_df, a dataframe, as well as three CSVs
"""
def scrape(is_search, target_company, search_value):
    try:
        global competitor
        competitor = target_company
        global webdriver_list
        main_driver = webdriver.Chrome(executable_path=path, options=options)
        webdriver_list.append(main_driver)
        global start_time
        start_time = time.time()
        if target_company == 'mayo':
            get_mayo_uofm_list(main_driver) # Create the unit of measure list
        main_driver.get(info_dict[target_company]['main_site'])
        
        if is_search:
            query = info_dict[target_company]['search_url']
            for word in re.split(r' ', search_value):
                query += str(word + info_dict[target_company]['search_separator'])
            print(f'query is {query}')
            main_driver.get(query)
            if target_company == 'mayo':
                test_link = main_driver.find_element(By.XPATH, '//div[@class="search_result"]/a').get_attribute('href')
            else:
                test_link = WebDriverWait(main_driver, 2).until(
                                EC.presence_of_element_located((By.XPATH, info_dict[target_company]['result_table_test_xpath']+ '//descendant::a[1]'))
                            ).get_attribute('href')
            search_dict = scrape_individual_test_page(test_link, target_company)
            final_df = pd.DataFrame.from_dict(search_dict)
        else:
            final_df = clean_dataframe(scrape_main_page(target_company, main_driver))
            create_final_output_files(final_df, 'finished')
        quit_webdrivers()
        return final_df
    except Exception as inst:
        send_error_email(str(inst), 'No link. Error caught in scrape function')
        quit_webdrivers()
        print('error caught in scrape: ', inst)
        raise
#         if run_type == 'Test': #This may create an infinite loop but will ensure that the code finishes
#             raise


# In[10]:


def create_metadata_file(dataframe):
    global start_time
    unique_tests = dataframe['TEST_NAME'].unique()
    metadata_dict = {'TIME_ELAPSED' : [str(int(time.time() - start_time))],
                     'NUM_UNIQUE_TESTS' : [len(unique_tests)],
                     'NUM_ROWS' : [len(dataframe.index)],
                     'NUM_NO_ANALYTES' : ['TEMP']
        
    }
    metadataframe = pd.DataFrame.from_dict(metadata_dict)
    metadataframe.to_csv(create_output_path('metadata', ''))
    


# In[11]:


#Empty for now
def clean_dataframe(dataframe):
    return dataframe


# In[12]:


def create_final_output_files(dataframe, status):
    global main_bad_tests_dict
    dataframe['TEST_NAME'] = dataframe['TEST_NAME'].str.upper() #df sorting needs consistent case
    dataframe = dataframe.sort_values(by=['TEST_NAME'])
#     letter_reached = dataframe.iloc[-1]['TEST_NAME'][0]
    letter_reached = 'NoLetterNotNecessary'
    dataframe = dataframe.reset_index(drop=True)
    df_output_path = create_output_path(status, letter_reached)
    dataframe.to_csv(df_output_path)
    bad_df = pd.DataFrame.from_dict(main_bad_tests_dict)
    bad_df = bad_df.drop_duplicates()
    bad_df.to_csv(create_output_path('bad', 'None'))
    check_errors(bad_df)
    if is_automated == True and status == 'finished' and run_type =='Full':
        CheckContents(dataframe)
        import upload_to_s3 as upload
        upload.upload_to_aws(df_output_path, bucket, 'FindMatches/competitor_compendia/' + csv_output_name + '.csv')
        upload.upload_to_aws(df_output_path, bucket, 'FindMatches/competitor_compendia/Archive/' + csv_output_name + run_type + datetime.now().strftime("%m-%d-%Y %H:%M:%S") + '.csv')

    create_metadata_file(dataframe)


# In[13]:


def CheckContents(df):
    df['new_col'] = df['TEST_NAME'].astype(str).str[0]
    df['new_col'] = df['new_col'][df['new_col'].str.match('[A-Z]')== True]
    num_letters = df['new_col'].nunique()
    unique_letters = df["new_col"].unique()
    error_detected = False
    error_msg = ''
    if num_letters < 26:
        error_detected = True
        error_msg += "Only had " + str(num_letters) + " letters: " + str(unique_letters) + "\n"
    df.drop(columns = ['new_col'])
    num_rows = len(df.index)
    if num_rows < info_dict[competitor]['num_rows']:
        error_detected = True
        error_msg += "Only had " + str(num_rows) + " rows. Minimum accepted value is: " + str(info_dict[competitor]['num_rows']) + "\n"
    if error_detected:
        send_error_email(error_msg, 'No link')


# In[14]:


def check_errors(df):
    print(df.columns)
    df_unique = df[df['ERROR_REASON'].astype(str).str.match('no such element') == False]
    df_unique = df_unique.groupby('ERROR_REASON')['PAGE_LINK'].nunique()
    error_msg = ''
    errored=False
    print(df_unique.index)
    for index in df_unique.index:
        page_link = df['PAGE_LINK'][df['ERROR_REASON'].str.match(index) == True]
        print(page_link)
        num_occurrs = df_unique[index]
        print(f'error: {index} occurrances: {num_occurrs}. Links are: \n{page_link}')
        if num_occurrs > 50:
            error_msg += f'\n{index} occurred {num_occurrs} times. Links are: \n{page_link}'
            errored=True
    if errored:
        send_error_email(error_msg, 'See above')
    return df_unique

# main_bad_tests_dict = {'ERROR_REASON': ['no such element: TEST_UNIT_OF_MEASURE', 'no such AHH: TEST_UNIT_OF_MEASURE'],
#  'PAGE_LINK': ['https://ltd.aruplab.com/Tests/Pub/0051174', 'https://ltd.aruplab.com/Tests/Pub/0051175']}

# # main_bad_tests_dict
# bad_df = pd.DataFrame.from_dict(main_bad_tests_dict)
# check_errors(bad_df)


# In[39]:





# In[15]:


def send_error_email(error, link):
    send_email("datateam@hc1.com", "Webscraper Failed", "Error: " + str(error) + '\nCompany: ' + competitor + '\nLink failed at: ' + link + '\nDate: ' + datetime.now().strftime("%m-%d-%Y %H:%M:%S"))


# # Overarching Function Call

# In[16]:



# for company in ['mayo', 'labCorp', 'arup']:
#     global competitor
#     competitor = company
#     final_dataframe = scrape(is_search, company, search_value)

#Doesn't run when importing
if __name__ == '__main__':
    final_dataframe = scrape(is_search, competitor, search_value)


# In[17]:


global_dataframe


# In[18]:


#final_dataframe


# In[ ]:



#NOTES

# # Pages with unique formatting

# In[19]:


#ARUP

#Two of the links that originally had an extra empty line above the mnemonic in the printout
# scrape_individual_test_page('https://ltd.aruplab.com/Tests/Pub/2001592', 'arup')
# scrape_individual_test_page('https://ltd.aruplab.com/Tests/Pub/0030191', 'arup')

#Has a big block that contains other tests as well
# scrape_individual_test_page('https://ltd.aruplab.com/Tests/Pub/2005639', 'arup')

#Covid header
# https://ltd.aruplab.com/Tests/Pub/3002723

#Has reference intervals but no analyte
# https://ltd.aruplab.com/Tests/Pub/0020407

#Ref interval has two table headings
# https://ltd.aruplab.com/Tests/Pub/0092420

#No interface map
# https://ltd.aruplab.com/Tests/Pub/2008915

#Has ref intervals in a table with multiple nested tables
# https://ltd.aruplab.com/Tests/Pub/2008915

#Ref interval returns text instead of JSON
# https://ltd.aruplab.com/Tests/Pub/0070490
# https://ltd.aruplab.com/Tests/Pub/2007211

#MAYO

#Has two specimen types in one block
# https://www.mayocliniclabs.com/test-catalog/Specimen/92360

#Has multiple cpt codes
# scrape_individual_test_page('https://www.mayocliniclabs.com/test-catalog/Fees+and+Codes/608251', 'mayo')

#Has analytes instead of "final delivery" etc
# scrape_individual_test_page('https://www.mayocliniclabs.com/test-catalog/Overview/113631', 'mayo')

#LOINC code is "in progress"
# https://www.mayocliniclabs.com/test-catalog/Fees+and+Codes/89009

#has specimen and "lavender top"
#https://www.mayocliniclabs.com/test-catalog/Specimen/89009

#Has no specimen
#https://www.mayocliniclabs.com/test-catalog/Specimen/63686

#TECHNICAL COMPONENT ONLY
#https://www.mayocliniclabs.com/test-catalog/Specimen/70493

#Has a lot of weird specimens
# https://www.mayocliniclabs.com/test-catalog/Specimen/64717

#Has duplicate LOINC code AND has multiple same CPT code with different descriptions
# https://www.mayocliniclabs.com/test-catalog/Fees+and+Codes/113528

#Bill only
# https://www.mayocliniclabs.com/test-catalog/Fees+and+Codes/63686

#Has a specimen stability that spans two columns
# https://www.mayocliniclabs.com/test-catalog/Specimen/113528

#Has a unit of measure that doesn't show up in the unit of measure list
# https://www.mayocliniclabs.com/test-catalog/Clinical+and+Interpretive/57707

#Has multiple instances of the same CPT code with different descriptions
# https://www.mayocliniclabs.com/test-catalog/Fees+and+Codes/35272

#Still a PROBLEM
#Has a reference interval table with a column that has colspan = 2 and the second column isn't gotten
# https://www.mayocliniclabs.com/test-catalog/Clinical+and+Interpretive/9248


#LABCORP

#Has a loinc table made up of multiple tables
# https://www.labcorp.com/tests/008851/urine-culture-prenatal-with-group-b-i-streptococcus-i-susceptibility-reflex

#Has multiple specimens
# https://www.labcorp.com/tests/500467/aldosterone-lc-ms-endocrine-sciences

#Has no loinc
# https://www.labcorp.com/tests/182949/occult-blood-fecal-immunoassay

#Has multiple loincs in one table
# https://www.labcorp.com/tests/231950/obstetric-panel-with-fourth-generation-hiv

#Has a specimen which includes instructions
# https://www.labcorp.com/tests/183764/acid-fast-mycobacteria-smear-and-culture-with-reflex-to-identification-and-susceptibility-testing

#Has a stability requirements table
# https://www.labcorp.com/tests/006056/abo-grouping

#Has a TON of reflex tabkes
# https://www.labcorp.com/tests/183764/acid-fast-mycobacteria-smear-and-culture-with-reflex-to-identification-and-susceptibility-testing

#Has Note: in specimen info that creates extra fields in JSON
# https://www.labcorp.com/tests/489067/epidermal-growth-factor-receptor-i-egfr-i-gene-mutation-analysis-non-small-cell-lung-cancer-real-time-pcr-version-two-assay


# In[20]:


# !curl https://intoli.com/install-google-chrome.sh | bash


# In[21]:


# !pip install selenium


# In[22]:


# re.search(mayo_mnemonic_regex, 'Test ID: AAABBR BBHH   ').group(0)


# In[23]:


# print(scrape_alphabetized_page('https://www.labcorp.com/test-menu/search?letter=U&page=4', 'labCorp'))


# In[24]:


# driver.quit()


# In[ ]:





# In[25]:


# print(scrape_individual_test_page('https://www.mayocliniclabs.com/test-catalog/Overview/70578', 'mayo'))

