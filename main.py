#!/usr/bin/env python
import xml.etree.ElementTree as ET
import urllib.request as request
from readability import Document
import configparser
from datetime import datetime, timedelta
import threading
import time
import pypandoc
import logging
import progressbar
import sys
import argparse

progressbar.streams.wrap_stderr()

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('rsspdf')
logging.getLogger('readability.readability').propagate = False


def message(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def rotatingbar(func):
    def wrapper(*args):
        widgets = [progressbar.AnimatedMarker(),
                   "  ",
                   progressbar.Timer()]
        bar = progressbar.ProgressBar(poll_interval=1, widgets=widgets)

        t = threading.Thread(target=func, args=args)
        t.start()

        while t.is_alive():
            bar.update()
            time.sleep(0.5)

        t.join()
        bar.finish()
    return wrapper


class Newspaper:

    def __init__(self):
        self._collections = []

    def render_html(self):
        fulltext = "<html><body>"
        for collection in self._collections:
            coll_text = \
                """
                <section class=collection>
                <h1>{name}</h1>
                {articles}
                </section>
                """.format(name=collection.name,
                           articles=collection.render_html())
            fulltext += coll_text
        fulltext += "</body></html>"
        return fulltext

    def download_all(self):
        message(self._collections)
        for collection in self._collections:
            message("=== %s ===" % collection.name)
            collection.download_feed()
            collection.download_articles()

    def add_collection(self, collection):
        self._collections.append(collection)

    @rotatingbar
    def export_pdf(self, filename, cli_args=None):
        args = [
            '--pdf-engine=xelatex',
            '-V', f'date:{datetime.now():%a %d %B %Y}',
        ]
        if cli_args.title:
            title = cli_args.title
            args += ['-V', f'title:"{title}"']
        if cli_args.pandoc_args:
            args += cli_args.pandoc_args

        message("Exporting to PDF...")
        pypandoc.convert_text(self.render_html(), 'pdf', 'html',
                              outputfile=filename, extra_args=args)


class Collection:
    _deltas = {
        'day': timedelta(days=1),
        'week': timedelta(days=7),
        'month': timedelta(days=30),
    }

    def __init__(self, urls, name):
        self.name = name
        self.urls = urls
        self._articles = []
        self._timedelta = None

    def set_allowed_timedelta(self, delta):
        if type(delta) == str:
            self._timedelta = self._deltas.get(delta)
        else:
            self._timedelta = delta

    def download_feed(self):
        for url in self.urls:
            self._download_url(url)

    def _download_url(self, url):
        message("Reading feed: %s" % url)
        with request.urlopen(url) as f:
            rss_text = f.read().decode('utf-8')
            root = ET.fromstring(rss_text)
            for channel in [c for c in root if c.tag == 'channel']:
                for item in [i for i in channel if i.tag == 'item']:
                    e_url = item.find('link')
                    e_title = item.find('title')
                    e_date = item.find('pubDate')
                    e_author = item.find('dc:creator')
                    if not e_url and e_title and e_date:
                        continue
                    else:
                        url = e_url.text
                        title = e_title.text
                        date = e_date.text
                    if e_author:  # non-standard
                        author = e_author.text
                        article = Article(url, title=title, date=date,
                                          author=author)
                    else:
                        article = Article(url, title=title, date=date)
                    now = datetime.now(tz=article.date.tzinfo)
                    if self._timedelta \
                            and now - article.date > self._timedelta:
                        continue
                    self._articles.append(article)

    def download_articles(self, limit=None):
        articles = self._articles if limit is None else self._articles[:limit]
        message("Downloading article texts...")
        bar = progressbar.ProgressBar(max_value=len(articles))
        for i, a in enumerate(articles):
            a.get_full_text()
            bar.update(i+1)
        bar.finish()

    def add_article(self, article):
        self._articles.append(article)

    def render_html(self):
        fulltext = ''
        for article in self._articles:
            date = article.date.strftime('%a, %d %b %H:%M')
            if article.author != 'Unknown':
                subtitle = "<em>{author}, {date}</em>".format(
                    author=article.author,
                    date=date
                )
            else:
                subtitle = "<em>{date}</em>".format(
                    date=date
                )
            fulltext += """<div class=article>
            <h1>{title}</h1>
            {subtitle}
            {body}
            </div>""".format(
                title=article.title,
                subtitle=subtitle,
                body=article.full_text)
        return fulltext


class Article:

    def __init__(self, url, **kwargs):
        self.url = url
        self.full_text = ''
        self.title = ''
        self.date = None
        self.author = 'Unknown'
        if kwargs.get('title'):
            self.title = kwargs['title']
        if kwargs.get('author'):
            self.author = kwargs['author']
        if kwargs.get('date'):
            date = kwargs['date']
            if type(date) == str:
                date = datetime.strptime(date, '%a, %d %b %Y %H:%M:%S %z')
            self.date = date

    def get_full_text(self):
        logger.debug('Downloading url: ' + self.url)
        with request.urlopen(self.url) as f:
            try:
                encoding = f.info().get_content_charset('utf-8')
                html = f.read().decode(encoding)
                self.full_text = Document(html).summary(html_partial=True)
            except UnicodeDecodeError:
                logger.error(
                    'UnicodeDecodeError (invalid charset) decoding: ' +
                    self.url)

    def __str__(self):
        return self.title + ' :: ' + self.url


def main():
    parser = argparse.ArgumentParser(
        description='Generate a PDF news digest from RSS feeds.')

    parser.add_argument('-t', '--title', dest='title', action='store',
                        help='The title of the pdf.')

    parser.add_argument('-o', '--output', dest='outputFile', action='store',
                        default="output.pdf",
                        help='Name of the output file')

    parser.add_argument('--no-toc', dest='toc', action='store_false',
                        default=True,
                        help='Disables table of contents')

    parser.add_argument('pandoc_args', action='store',
                        metavar='-- PANDOC_FLAGS', nargs='*',
                        help='Additional flags to pass to pandoc')

    args = parser.parse_args()

    config = configparser.ConfigParser()
    config.read('config.ini')

    newspaper = Newspaper()

    feeds = [config[i] for i in config if i.startswith('feed.')]
    # parse global
    timedelta = None
    if 'general' in config:
        general = config['general']
        if 'last' in general:
            timedelta = general['last']
    for feed in feeds:
        urls = feed['url'].split(',')
        collection = Collection(urls, feed['name'])
        if feed.get('last'):
            collection.set_allowed_timedelta(feed['last'])
        elif timedelta is not None:
            collection.set_allowed_timedelta(timedelta)
        newspaper.add_collection(collection)

    newspaper.download_all()
    newspaper.export_pdf(args.outputFile, args)
    # print(newspaper.render_html())


if __name__ == "__main__":
    main()
