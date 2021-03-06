#!/usr/bin/env python3

"""
.. module:: download_stenos

   :synopsis: Parses all the steneoprotocols of the parlament and creates
text files tagged the following way

    s_<ddd>_<yyyymmdd>_b<ddd>_i_<ddd>_<name_str>.txt

    - s_<ddd>        theee digits indicating the session
    - <yyyymmdd>     date of the intervention
    - t_<ddd>        order of the day point index
    - i_<ddd>        intervention index
    - <name_str>     name of the speaker

.. moduleauthor:: Manuel Berrocal <mbercas@gmail.com>

"""
"""
GNU General Public License v3.0
Permissions of this strong copyleft license are conditioned on making available complete source code of licensed works and modifications, which include larger works using a licensed work, under the same license. Copyright and license notices must be preserved. Contributors provide an express grant of patent rights.
"""



import os, sys
import re
import logging
from bs4 import BeautifulSoup
import requests
import argparse

from pathlib import Path
from collections import namedtuple

class SessionManager:
    __slots__ = ['valid', 'title', 'index', 'date', 'base_session_url']
    def __init__(self):
        self.valid = False
        self.index = ""
        self.date  = ""
        self.title = ""
        self.base_session_url = ""

    def __str__(self):
        str_ = "Title: {}".format(self.title)
        str_ += "Index: {}".format(self.index)
        str_ += "Date string: {}".format(self.date)
        str_ += "URL: {}".format(self.base_session_url)
        return str_

CzechMonths = {'ledna':1, 'února':2, 'března':3,'dubna':4,'května':5,
               'června':6,'července':7,'srpna':8, 'září':9,
               'října':10, 'listopadu':11, 'prosince':12 }


def get_all_stenos(res, year):
    """Gets the content page of PSP and returns all the links to the prococols"""
    soup_main = BeautifulSoup(res, 'html5lib')
    if year >= 2010:
        reg_ex_steno_main = re.compile(r'^.*schuz.*htm[l]?$')
    else:
        reg_ex_steno_main = re.compile(r'^.*schuz/$')
    return [l.get('href') for l in soup_main.find_all('a') if None != reg_ex_steno_main.search(l.get('href'))]


def check_request(res):
    """Returns False if the request failed"""
    rc = True
    if res.status_code == requests.codes.ok:
        logging.info("Connected to page %s", steno_page_url)
        if steno_page_url == "http://psp.cz/eknih/2010ps/stenprot/index.htm":
            print("found")
    else:
        logging.error("Unable to open page: %s", steno_page_url)
        rc = False
    return rc


# Define some data types for collections of the data
InterventionInfo = namedtuple('InterventionInfo', ['pageref', 'stenopage', 'reftag', 'steno_name', 'date'])
Intervention = namedtuple('Intervention', ['stenoname', 'text', 'speaker_key'])
Speaker = namedtuple('Speaker', ['stenoname', 'pagename', 'name', 'titles', 'function',
                                 'sex', 'group', 'birthdate', 'link'])


class SessionParser:

    class Page:
        def __init__(self):
            self.link = ""
            self.date_string = ""
            self.content = ""
            self.soup = None

    def __init__(self, year, base_url, session_number, session_link):

        self.year = year
        self.base_url = base_url
        self.sublinks = base_url + session_number + "schuz/"
        self.session_link = base_url + session_link
        self.session_number = int(session_number)
        self.session_soup = None
        self.pages = {}    # pages link stenos and order them by topic
        self.stenos = {}
        self.topics = {}
        self.topic_titles = {}
        self.interventions_info = {}
        self.speakers = {}
        self.request_counter = 0
        self.visited_links = {}

        self.cache = Path('.') / '.cache'
        if not self.cache.exists():
            self.cache.mkdir(parents=True)


    def request(self, link):
        """Manages the request to the link and collect statistis

        Before making a connection checks if the file can be retrieved
        from cache.

        :param link str: link to the page to request
        :rtype str: the contents of the web page in a string"""

        file_str = link.replace('http://public.psp.cz/eknih/', '')

        cached_file_name = self.cache / file_str
        text = ""


        if cached_file_name.exists():
            logging.debug(f"{cached_file_name} ...reusing")
            text = cached_file_name.read_text(encoding='utf-8')
        else:
            res = requests.get(link)

            self.request_counter += 1
            if False == check_request(res):
                raise Exception()

            cached_file_name.parents[0].mkdir(parents=True, exist_ok=True)
            cached_file_name.write_text(res.text, encoding='utf-8')
            text = res.text
        return text


    def parse_session_post_2013(self):

        # All topics are between <p>...</p>
        for topic in self.session_soup.find_all('p'):
            # topics have <a> id="<identifier>" name="<identifier>"</a>
            # and a set of links
            links = topic.find_all('a')
            if len(links) == 0:
                continue

            # Try to read id = 'b<number>' and remove the 'b'
            try:
                topic_id = int(links[0]['id'][1:])
            except KeyError:
                logging.info("Ignoring: %s", links[0])
                continue

            if topic_id not in self.topics:
                self.topics[topic_id] = []
                self.topic_titles[topic_id] = links[0].next_sibling.text


            for link in links[1:]:
                try:
                    sublink = link['href']

                    if "/sqw/historie.sqw" not in sublink:
                        q_id = self.get_qid_for_topic(sublink)
                        if None == q_id:
                            logging.warning("Can not find q_id in %s", sublink)
                            continue
                    else:
                        continue

                    if self.parse_sublink_order(q_id, sublink):
                        self.topics[topic_id].extend(self.interventions_info[q_id])
                except KeyError:
                    continue

    def parse_session_2013(self):
        """
        All topics start ia <a name="b >,
        all links go below topic are of the form < a href=
        """
        links = self.session_soup.find_all('a')
        reg_ex_topic = re.compile('^.*html#(q[\d]+)$')

        topic_id = 0
        for link in links:
            # first find the topic
            # Try to read name = 'b<number>' and remove the 'b'
            try:
                topic_id = int(link['name'][1:].replace('b',''))
                if topic_id not in self.topics:
                    self.topics[topic_id] = []
                    self.topic_titles[topic_id] = self.filter_text(link.next_sibling.text)
                    logging.debug(f"{self.topic_titles[topic_id]=} - {topic_id}")
                    continue

            except KeyError:
                logging.debug("Ignoring: %s", link)


            try:
                sublink = link['href']

                if None != reg_ex_topic.match(sublink):
                    hash_id = self.get_hash_for_topic(sublink)
                    # print(f"{sublink=} -> {hash_id=}")
                    if None == hash_id:
                        logging.warning("Can not find hash in %s", sublink)
                        continue
                else:
                    continue

                if self.parse_sublink_order(hash_id, sublink):
                    self.topics[topic_id].extend(self.interventions_info[hash_id])
            except KeyError:
                continue


    def parse_session_pre_2013(self):
        """
        All topics start ia <a name="b >,
        all links go below topic are of the form < a href=
        """
        links = self.session_soup.find_all('a')
        reg_ex_topic = re.compile('^.*html#([\d]+)$')

        topic_id = 0
        for link in links:
            # first find the topic
            # Try to read name = 'b<number>' and remove the 'b'
            try:
                topic_id = int(link['name'][1:].replace('b',''))
                if topic_id not in self.topics:
                    self.topics[topic_id] = []
                    self.topic_titles[topic_id] = self.filter_text(link.next_sibling.text)
                    logging.debug(f"{self.topic_titles[topic_id]=} - {topic_id}")
                    continue

            except KeyError:
                logging.debug("Ignoring: %s", link)


            try:
                sublink = link['href']

                if None != reg_ex_topic.match(sublink):
                    hash_id = self.get_hash_for_topic(sublink)
                    # print(f"{sublink=} -> {hash_id=}")
                    if None == hash_id:
                        logging.warning("Can not find hash in %s", sublink)
                        continue
                else:
                    continue

                if self.parse_sublink_order(hash_id, sublink):
                    self.topics[topic_id].extend(self.interventions_info[hash_id])
            except KeyError:
                continue


    def parse_session(self):
        """
        The main page of the session contains all the links to all the subsessions,
        they are ordered by topic (topics can be split in different days (i.e. so
        they are stored in different pages), we will transverse the session following
        the links in the session record (Schuz)

        Returns False if ti fails processing the session (Schuz)

        session -> topic -> intervention

        """

        logging.info("Parsing session %s", self.session_link)

        try:
            text = self.request(self.session_link)
        except Exception:
            return False

        main_soup =  BeautifulSoup(text, 'html5lib')
        self.session_soup = main_soup

        if self.year == 2013:
            self.parse_session_2013()
        elif self.year > 2013:
            self.parse_session_post_2013()
        else:
            self.parse_session_pre_2013()

        # All links to interventions are now in self.interventions
        # first download all individual pages into stenos dictionary
        #
        self.get_all_stenos()

    def get_all_stenos(self):
        """Iterate the interventions dictionary to download all the pages of
        the stenos, parse them and strore them in the stenos dictionary"""
        for topic in self.topics.values():
            if len(topic) == 0:
                continue

            for int_info in topic:
                if int_info.stenopage not in self.stenos:
                    link = self.sublinks + int_info.stenopage

                    try:
                        text = self.request(link)
                    except Exception:
                        logging.error("Can not open steno page %s", link)
                        continue

                    # All paragraphs with text are justified
                    text = text #.lower()
                    soup =  BeautifulSoup(text, 'html5lib')
                    self.stenos[int_info.stenopage] = self.parse_steno(soup)

    def parse_steno(self, steno):
        """Parse the steno text and generate a interventions dictionary
        The interventions is a dictionary containing the topic id (r<nn>)
        as a key and tupple with the speker and text for the intervention.
        """
        r_id = ""
        text = ""
        speaker = ""
        interventions = {}

        # remove the parts of the page that do not contain information
        #soup.head.decompose()
        #soup.find('div', id='header').decompose()
        #soup.find('div', id='menu').decompose()
        #soup.find('div', id='tools').decompose()
        #soup.find('div', id='footer').decompose()

        #[s.decompose() for s in soup.find_all('script')]


        steno = steno.find("div", id='main-content')
        [div.decompose() for div in steno.find_all("div")]

        #remove all centered paragraphs - they contain headers
        [p.decompose() for p in steno.find_all('p', attrs={'align':'center'})]
        [p.decompose() for p in steno.find_all('center')]

        # aligned paragraphs do only exist after 1996
        #text_paragraphs = steno.find_all('p', attrs={'align':'justify'})
        text_paragraphs = steno.find_all('p')

        # print(f">> {len(text_paragraphs)=}")

        speaker_key = ""
        for p in text_paragraphs:
            # ignore empty
            if p.text == '\xa0' or p.text == '':
                continue
            
            speaker_link = p.find('a')

            # print(f" >> >> >> {speaker_link=}")
            #if speaker_link and speaker_link.has_attr('id') and speaker_link.has_attr('href') and 'hlasy.sqw' not in speaker_link['href']:
            if speaker_link and speaker_link.has_attr('id'):
                if speaker_link.has_attr('href'):
                    if 'hlasy.sqw' in speaker_link['href']: #or "historie.sqw" in speaker_link['href']:
                        #text += self.filter_text(speaker_linkp.text)
                        continue
                if speaker_link.text == "":
                    continue

                if r_id != "":
                    interventions[r_id] = Intervention(stenoname=speaker, text=text.strip(), speaker_key=speaker_key)
                text = ""
                #if speaker_link.has_attr('id') and 'hlasy.sqw' not in speaker_link['href']:
                if speaker_link.has_attr('id'):
                    r_id = speaker_link['id']

                    # some names have a : at the end - remove
                    speaker_link_text = self.filter_text(speaker_link.text)

                    # old stenos have no href use steno name as key instead

                    if speaker_link_text[-1] == ":":
                        speaker_link_text = speaker_link_text[:-1]

                    speaker = speaker_link_text.strip().replace(' ', '_')
                    speaker = speaker.replace(',', '_').replace('__', '_')

                    speaker_key = speaker
                    try:
                        speaker_page = speaker_link['href']
                    except:
                        speaker_page = ""                  

                    if speaker_key not in self.speakers:
                        logging.info("New speaker found: %s", speaker_link_text)
                        self.speakers[speaker_key] = Speaker(speaker_link_text, "", "", "", "", "", "", "", speaker_page)

                speaker_link.extract()

            text += self.filter_text(p.text.strip()) + "\n"
        if r_id != "":
            interventions[r_id] = Intervention(stenoname=speaker, text=text.strip(), speaker_key=speaker_key)
        return interventions


    def parse_speakers(self):

        regex = re.compile("/sqw/detail.sqw\?id=(\d+)$")
        for key, speaker in self.speakers.items():

            name = ""
            group = ""
            function = ""
            sex = ""
            birth_date = ""
            page_name = ""

            if len(speaker.name) > 0:
                continue

            if "https://www.vlada.cz/cz/" in speaker.link:
                try:
                    text = self.request(speaker.link)
                except Exception:
                    logging.error("Failed retrieving info for {}", speaker.stenoname)
                    sys.exit(-1)
                soup = BeautifulSoup(text, 'html5lib')
                page_name = self.filter_text(soup.find('h1').text)
            elif "/sqw/detail.sqw" in speaker.link:
                idx = regex.search(speaker.link)
                if idx:

                    link = "http://www.psp.cz/" + speaker.link


                    try:
                        text = self.request(link)
                    except Exception:
                        logging.error("Failed retrieving info for {}", speaker.values().stenoname)
                        sys.exit(-1)

                    soup = BeautifulSoup(text, 'html5lib')

                    page_name = self.filter_text(soup.find('h1').text)

                    figcaption =  soup.find_all("div", attrs={"class": "figcaption"})

                    if figcaption != []:
                        text = self.filter_text(figcaption[0].text)
                        if "Zvolen" in text:
                            figregex = re.compile(r"Narozen.?: ([\d]+)\..(\d+)\..(\d+).*Zvolen.? na kandidátce: (.*)$")
                            figgs = figregex.search(text)
                            if figgs:
                                group = figgs.groups()[3]
                        else:
                            figregex = re.compile(r"Narozen: ([\d]+)\..(\d+)\..(\d+)$",
                                              re.DOTALL)

                            figgs = figregex.search(text)

                        if figgs:
                            birth_date = "{0:0>4}{1:0>2}{2:0>2}".format(figgs.groups()[2],
                                                                        figgs.groups()[1],
                                                                        figgs.groups()[0])

            (name, titles, function, sex) = self.get_speakers_name(page_name, speaker.stenoname)
            self.speakers[key] = Speaker(stenoname=speaker.stenoname,
                                         pagename=page_name,
                                         name=name,
                                         titles=titles,
                                         function=function,
                                         sex=sex,
                                         group=group,
                                         birthdate=birth_date,
                                         link=speaker.link)

    def get_speakers_name(self, page_name, steno_name):
        """Uses the steno name and page name to extract the filtered name
           the function in the parliament and the title"""

        title_strings = ["doc.", "Prof.", "RSDR.", "RSDr.", "RNDr.","Ing.", "JUDr.", "PhDr.", "Mgr.", "MBA", "ThMgr.", "CSc.",
                             "PaedDr.", "Ph.D.", "MUDr.", "Bc.", "arch.", "Doc.", "MVDr.", "Th"
                             "prof.", "MVDR.", "MgA.", "PhD.JU", "ThDr.", "PhD.", "DrSc.", "Dr."]


        titles = ""
        page_name = page_name.replace(',', '').strip()
        for title in title_strings:
            if title in page_name:
                titles += title + " "
                page_name = page_name.replace(title, "").strip()
        titles = titles.strip()

        name = page_name
        function = steno_name.replace(page_name, "").strip()


        male_strings = ["Poslanec", "Ministr", "Místopředseda", "Předseda", "Senátor","poslanec", "ministr", "místopředseda", "předseda", "senátor"]
        female_strings = ["Poslankyně",  "Ministryně", "Členka", "Senátorka", "Místopředsedkyně", "poslankyně",  "ministryně", "členka", "senátorka", "místopředsedkyně"]
        sex = ""
        for female_string in female_strings:
            if female_string in function:
                sex = "Woman"
                break
        if sex == "":
            for male_string in male_strings:
                if male_string in function:
                    sex = "Man"
                    break


        return (name, titles, function, sex)

    def filter_text(self, text):

        if len(text) == 0:
            return ""

        # remove : at beginning of paragraph
        if text[0] == ':':
            text = text[1:].strip()

        # replace '\xa0' with space
        text = text.replace('\xa0', ' ')

        # replace multiple spaces with one, and remove white spaces
        # from beginning and end
        text = re.sub( '\s+', ' ', text).strip()

        return text

    def generate_files_and_report(self, output_directory=Path('.'), create_new_report=True):
        """Iterate the topics dictionary to get all the intrventions per
        topic, then go to the stenos dictionary to print get intervention"""
        if not output_directory.exists():
            output_directory.mkdir(parents=True)

        csv_file = output_directory.joinpath("file_summary.tsv")

        if not csv_file.exists():
            create_new_report = True

        if create_new_report:
            open_str = 'w+'
        else:
            open_str = 'a+'

        count = 0
        with csv_file.open(open_str) as report_fd:
            tsv_line = "session\tdate\ttopic_idx\ttopic_str\torder\tname\tsteno_name\tfile_name\n"

            if create_new_report:
                report_fd.write(tsv_line)

            visited_links = {}
            for topic_id, topic in self.topics.items():
                logging.debug(f"{topic_id=} -> {len(topic)=}")
                for idx, int_info in enumerate(topic):
                    try:
                        if int_info.stenopage not in visited_links:
                            visited_links[int_info.stenopage] = []
                        else:
                            if int_info.reftag in visited_links[int_info.stenopage]:
                                logging.warning(f"GENERATE_FILES: Skipping already visitied {int_info.reftag} in steno {int_info.stenopage}")
                                continue
                            else:
                                visited_links[int_info.stenopage].append(int_info.reftag)

                        steno = self.stenos[int_info.stenopage][int_info.reftag]
                        # print(f"{steno.stenoname=}")
                        file_name = self.generate_file_name(int_info.date,
                                                            topic_id,
                                                            idx+1,
                                                            steno.stenoname)
                        full_file_name = output_directory.joinpath(file_name)

                        with full_file_name.open('w', encoding = 'utf-8') as fd:
                            fd.write(steno.text)

                            tsv_line = "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n".format(
                                self.session_number,
                                int_info.date,
                                topic_id,
                                self.topic_titles[topic_id],
                                idx+1,
                                self.speakers[steno.speaker_key].name,
                                steno.stenoname,
                                file_name)
                            report_fd.write(tsv_line)


                        count += 1
                    except KeyError:
                        logging.error(f"GENERATE_FILES: Can not find key {int_info.reftag} in steno {int_info.stenopage}")

                        #logging.error("Can not find key %s in steno %s",
                        #              int_info.reftag, int_info.stenopage)
        logging.info(f"GENERATE FILES: {count} files generated")


    def generate_speakers_report(self, output_directory, speakers, create_new_report):
        if not output_directory.exists():
            output_directory.mkdir(parents=True)

        csv_file = output_directory.joinpath("speakers_summary.tsv")

        if not csv_file.exists():
            create_new_report = True

        if create_new_report:
            open_str = 'w+'
        else:
            open_str = 'a+'

        with csv_file.open(open_str) as fd:
            tsv_line = "name\ttitles\tfunction\tsteno_name\tsex\tparty\tbirthdate\tweb_page\n"

            if create_new_report:
                fd.write(tsv_line)

            for page, speaker in speakers.items():
                tsv_line = "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\n".format(
                    speaker.name,
                    speaker.titles,
                    speaker.function,
                    speaker.stenoname,
                    speaker.sex,
                    speaker.group,
                    speaker.birthdate,
                    page)
                fd.write(tsv_line)


    def generate_file_name(self, date_string, topic_id, order, name):
        """Generate the file name string
        :param data_string str: a string containing the date
        :param topic_id str: a string containing the topic id
        :param order int: a number indicating the intervention ordor for the topic
        :param name str: a string containing the speaker name
        :rtype: a string containing the file name
        """
        file_name = 's_{0:0>3}_{1}_t_{2:0>3}_i_{3:0>3}_{4}.txt'.format(self.session_number,
                                                                 date_string,
                                                                 topic_id,
                                                                 order,
                                                                 name)
        return file_name


    def parse_sublink_order(self, order_id, sublink):

        if self.year >= 2010:
            reg_ex_page = re.compile('^(.*.html).*')
        else:
            reg_ex_page = re.compile('^.*schuz/(.*.html).*')

        page_name = reg_ex_page.match(sublink)

        if None == page_name:
            logging.error("Can not find page name in sublink %s", sublink)
            return False

        if self.year >= 2010:
            page_idx = page_name.group(1)
        else:
            page_idx = page_name.group(1) #sublink

        if page_idx not in self.pages:
            if self.year >= 2010:
                link = self.sublinks + sublink
            else:
                link = self.sublinks + page_name.group(1)

            try:
                text = self.request(link)
            except Exception:
                return False

            page = self.Page()
            page.link = link
            page.content = text
            page.soup = BeautifulSoup(text, 'html5lib')
            (rc, date) = self.get_steno_date(page.soup)
            if False == rc:
                logging.error("Can not find date in steno %s", link)
                return False
            page.date_string = date
            self.parse_interventions_page(page.soup, date)
            self.pages[page_idx] = page

        return True

    def parse_interventions_page(self, page_soup, date):
        """Get a list of all the q tags and all the a links below"""
        a_links = page_soup.find_all('a')

        intervention_link = re.compile('(s[\d]*.htm)#(r[\d]*)$')

        q_id = ""
        for link in a_links:
            # print(f"{link}")
            if link.has_attr('name'):
                q_id = link['name']
                if q_id not in self.interventions_info:
                    self.interventions_info[q_id] = []
            elif link.has_attr('href') and q_id != "":
                info = intervention_link.search(link['href'])

                if None != info:
                    steno_name = self.filter_text(link.text)
                    new_intervention_info = InterventionInfo(pageref=info.group(0),
                                                             stenopage=info.group(1),
                                                             reftag=info.group(2),
                                                             steno_name=steno_name,
                                                             date=date)
                    if new_intervention_info not in self.interventions_info[q_id]:
                        self.interventions_info[q_id].append(new_intervention_info)


    def get_qid_for_topic(self, link):
        """
        Find q# boundary <a id="q\d>, then find all the
        <a href="s[\d]6.html#r[\d]+ until the next q\d
        for all the links get the page if not allready in
        stenos and extract the text for a given person
        """
        reg_ex_topic = re.compile('^.*html#(q[\d]+)$')
        topic  = reg_ex_topic.match(link)
        if None == topic:
            logging.warning("Could not find 'q' topic separator in %s", link)
            return None

        return topic.group(1)

    def get_hash_for_topic(self, link):
        """
        Find q# boundary <a id="\d>, then find all the
        <a href="s[\d]6.html#r[\d]+ until the next q\d
        for all the links get the page if not allready in
        stenos and extract the text for a given person
        """
        if year == 2013:
            reg_ex_topic = re.compile('^.*html(#[a-z][\d]+)$')
        else:
            reg_ex_topic = re.compile('^.*html#([\d]+)$')
        topic  = reg_ex_topic.match(link)
        if None == topic:
            logging.warning("Could not find '#' topic separator in %s", link)
            return None

        return topic.group(1)

    def get_steno_date(self, soup):
        """Find metadata of the stenotype on the title.
        Returns a set containin valid if the title is valid,
        index of the session, and date in yyyymmdd format"""


        title = soup.find('title').string

        if len(title) == 0:
            return (False, "")

        title = title.replace('\xa0', ' ')

        reg_ex_title_date = re.compile(r'Stenografický zápis [\d]+. schůze, ([\d]+).\s(.*)\s(\d{4})')
        d = reg_ex_title_date.search(title)
        if d == None:
            logging.error("Can not find date in title: %s", title)
            return (False, "")

        date = "{0}{1:0>2}{2:0>2}".format(d.group(3), CzechMonths[d.group(2)], int(d.group(1)))
        return (True, date)

def filter_names_and_titles(name):
    stop_words = ["PhDr.", "Ing.", "prof.", "JUDr." "RSDr.", "Mgr.",
                  "arch.", "RNDr.", "MVDR.", "MgA.", "MUDr.", "ThDr.",
                  "MBA", "doc." "CSc.", "PaedDr.", "Bc.", "PhD.", "DrSc.",
                  "Ph.D."]
    titles = ""
    for word in stop_words:
        pos = name.lower().find(word.lower())
        if pos != -1:
            titles += word + " "
            name = name[:pos] + name[pos + len(word):]

    name = name.replace(',', '')

    return (name.strip(), titles.strip())


def parse_args():
    """Parses and validates the command line arguments
    :rtype: argparser.args object
    """

    valid_years = ["1993", "1996", "1998", "2002", "2006", "2010", "2013", "2017"]

    parser = argparse.ArgumentParser(description='Download steno-protocols in psp.cz')
    parser.add_argument('--index', action='store_true', default=False,
                        dest='generate_index',
                        help='generate an index for the files')
    parser.add_argument('-o', '--output-dir',action='store', default='.',
                        dest='output_directory',
                        help='output directory')
    parser.add_argument('-y', '--year', action='store', default='2017',
                        dest='year',
                        help=f'session year {valid_years}')
    parser.add_argument('-n', '--new-report', action='store_true', default=False,
                        dest='create_new_report',
                        help='creates a new report for data dowdloaded if already '
                            + 'exists, otherwise creates a new one')

    args = parser.parse_args()


    if args.year not in valid_years:
        print(f"Invalid session year, valid years are {valid_years}")
        logging.error("(): Invalid session year".format(args.year))
        sys.exit(-1)

    return args


if __name__ == "__main__":

    #FORMAT = "[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s"
    FORMAT = "[%(lineno)s - %(funcName)20s() ] %(message)s"
    logging.basicConfig(format=FORMAT, filename='download_stenos.log', level=logging.INFO)

    args = parse_args()
    year = int(args.year) # 1993, 1996, 1998, 2002, 2006, 2010, 2013 or 2017


    if int(year) >= 2010:
        base_page_url = f"http://psp.cz/eknih/{year}ps/stenprot/"
    else:
        base_page_url = f"http://public.psp.cz/eknih/{year}ps/stenprot/"
    steno_page_url = base_page_url + 'index.htm'


    res = requests.get(steno_page_url)

    if check_request(res) == False:
        logging.error("Can not connect to page: {}".format(steno_page_url))
        exit(-1)

    # get the links for all session pages
    #
    session_links = get_all_stenos(res.text, year)

    #base = set([link[:9]+"index.htm" for link in session_links])

    #session_links = list(base) + session_links

    #m = re.compile('^([\d]+)schuz/.+\.htm[l]?$')
    m = re.compile('^([\d]+)schuz/index.htm$')
    create_new_report = args.create_new_report
    request_counter = 0
    print(f"{len(session_links)=}")
    session = None
    speakers = {}
    for idx, link in enumerate(session_links):

        if year < 2010:
            link += 'index.htm'
        session_id = m.match(link)
        print(f'id:{idx} - link: {link}')
        if session_id == None:
            logging.debug("Can not get session number from link %s", link)
            continue

        session = SessionParser(year, base_page_url, session_id.group(1), link)
        session.speakers = speakers

        session.parse_session()
        session.parse_speakers()

        speakers = {**speakers, **session.speakers}  # requires python >=3.5
        #session.generate_files(Path(args.output_directory))
        #session.generate_report(Path(args.output_directory), create_new_report)
        output_directory = Path(args.output_directory)
        session.generate_files_and_report(output_directory, create_new_report)

        request_counter += session.request_counter
        print("Completed session {}: accesses {} / cum. {}\n".format(session_id.group(1),
                                                                     session.request_counter,
                                                                     request_counter))

        create_new_report = False

    session.generate_speakers_report(Path(args.output_directory),
                                     speakers, True)
