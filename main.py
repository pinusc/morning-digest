#!/usr/bin/env python
import feedparser
import urllib.request as request
from urllib.error import HTTPError
from readability import Document
import configparser
from datetime import date, timedelta
from time import mktime
import threading
import time
import pypandoc
import logging
import progressbar
import sys
import argparse

FILTERFILE = 'filters.py'

progressbar.streams.wrap_stderr()

logger = logging.getLogger('rsspdf')
logging.getLogger('readability.readability').propagate = False


def message(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


def rotatingbar(func):
    def wrapper(*args, **kwargs):
        widgets = [progressbar.AnimatedMarker(),
                   "  ",
                   progressbar.Timer()]
        bar = progressbar.ProgressBar(poll_interval=1, widgets=widgets)

        t = threading.Thread(target=func, args=args, kwargs=kwargs)
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
            html = collection.render_html()
            if html == '':
                continue
            coll_text = \
                """
                <section class=collection id={collectionid}>
                <h1>{name}</h1>
                {articles}
                </section>
                """.format(name=collection.name,
                           collectionid=collection.id,
                           articles=html)
            fulltext += coll_text
        fulltext += "</body></html>"
        return fulltext

    def download_all(self):
        message(self._collections)
        for collection in self._collections:
            message("=== %s ===" % collection.name)
            collection.download_feed()
            if collection.fetch_original:
                collection.download_articles()

    def add_collection(self, collection):
        self._collections.append(collection)

    @rotatingbar
    def export(self, filename, out_format, *,
               metadata_file=None, defaults_file=None,
               filters=None, pandoc_args=None, title=None):
        args = [
            '-F', FILTERFILE,
            '-M', 'date=' + date.today().strftime('%A, %B %e, %Y')]
        if out_format == 'pdf':
            args.append('--pdf-engine=xelatex')

        if metadata_file is not None:
            args.append('--metadata-file=' + metadata_file)
        if defaults_file is not None:
            args.append('--defaults=' + defaults_file)
        if filters is not None:
            for filterf in filters:
                args += ['-F', filterf]
        if title is not None:
            args += ['-V', f'title:"{title}"']
        if pandoc_args is not None:
            args += pandoc_args

        message(f"Exporting to {out_format}...")
        if out_format == 'html_raw':
            with open(filename, 'w') as f:
                f.write(self.render_html())
        else:
            pypandoc.convert_text(self.render_html(), out_format, 'html',
                                  outputfile=filename, extra_args=args)


class Collection:
    _deltas = {
        'day': timedelta(days=1),
        'week': timedelta(days=7),
        'month': timedelta(days=30),
    }

    def __init__(self, collection_id, urls, name, add_title=True):
        self.name = name
        self.id = collection_id
        self.urls = urls
        self._articles = []
        self._timedelta = None
        self.fetch_original = False
        self.add_title = add_title

    def set_allowed_timedelta(self, delta):
        if type(delta) == str:
            if delta in self._deltas:
                self._timedelta = self._deltas.get(delta)
            else:
                try:
                    self._timedelta = timedelta(days=int(delta))
                except ValueError:
                    message("Invalid value passed for 'last' field: " + delta)
                    sys.exit(1)
        else:
            self._timedelta = delta

    def download_feed(self):
        for url in self.urls:
            self._download_url(url)

    def _download_url(self, url):
        message("Reading feed: %s" % url)
        d = feedparser.parse(url)
        now = date.today()
        for entry in d.entries:
            if 'link' not in entry or 'title' not in entry:
                continue

            attrs = {}

            if 'author' in entry:
                attrs['author'] = entry['author']
            if 'title' in entry:
                attrs['title'] = entry['title']
            if 'published_parsed' in entry:
                dt = date.fromtimestamp(mktime(entry['published_parsed']))
                attrs['date'] = dt
            if 'description' in entry:
                attrs['full_text'] = entry['description']

            article = Article(entry.link, **attrs)
            if self._timedelta \
                    and now - article.date > self._timedelta:
                continue
            self._articles.append(article)
        return

    def download_articles(self, limit=None):
        articles = self._articles if limit is None else self._articles[:limit]
        if len(articles) == 0:
            message("No suitable articles found!")
            return
        message("Downloading article texts...")
        bar = progressbar.ProgressBar(marker='=', max_value=len(articles))
        for i, a in enumerate(articles):
            a.get_full_text()
            bar.update(i+1)
        bar.finish()

    def add_article(self, article):
        self._articles.append(article)

    def _sort(self):
        self._articles.sort(key=lambda x: x.date, reverse=True)

    def render_html(self):
        fulltext = ''
        self._sort()
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
            if self.add_title:
                fulltext += """<div class="article morning-digest-article">
                <h1>{title}</h1>
                {subtitle}
                {body}
                </div>""".format(
                    title=article.title,
                    subtitle=subtitle,
                    body=article.full_text)
            else:
                fulltext += """<div class="article morning-digest-article">
                {body}
                </div>""".format(body=article.full_text)
        return fulltext


class Article:
    headers = {

    }

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
            self.date = kwargs['date']
        if kwargs.get('full_text'):
            self.full_text = kwargs['full_text']

    def get_full_text(self):
        logger.debug('Downloading url: ' + self.url)
        req = request.Request(self.url)
        req.add_header('Referer', 'https://www.google.com/')
        req.add_header('User-Agent',
                       'Mozilla/5.0 (compatible; Googlebot/2.1;' +
                       '+http://www.google.com/bot.html)')
        try:
            with request.urlopen(req) as f:
                encoding = f.info().get_content_charset('utf-8')
                html = f.read().decode(encoding)
                self.full_text = Document(html).summary(html_partial=True)
        except UnicodeDecodeError:
            logger.error(
                'UnicodeDecodeError (invalid charset) decoding: ' +
                self.url)
        except HTTPError:
            logger.error(
                'HTTP Error while downloading URL' + self.url)
            message(HTTPError)

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

    parser.add_argument('--debug', dest='debug', action='store_true',
                        default=False,
                        help='Print debug info')

    parser.add_argument('--no-toc', dest='toc', action='store_false',
                        default=True,
                        help='Disables table of contents')

    parser.add_argument('--format', dest='output_format', action='store',
                        default='pdf', help='Output format')

    parser.add_argument('-c', '--config', dest='config_file', action='store',
                        default='config.ini', help='Config file')

    parser.add_argument('pandoc_args', action='store',
                        metavar='-- PANDOC_FLAGS', nargs='*',
                        help='Additional flags to pass to pandoc')

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

    config = configparser.ConfigParser()
    config.read(args.config_file)

    newspaper = Newspaper()

    feeds = [config[i] for i in config if i.startswith('feed.')]
    # parse global
    timedelta = None
    exportkwargs = {}
    if 'general' in config:
        general = config['general']
        if 'last' in general:
            timedelta = general['last']
        if 'metadata-file' in general:
            exportkwargs['metadata_file'] = general['metadata-file']
        if 'defaults-file' in general:
            exportkwargs['defaults_file'] = general['defaults-file']
        if 'filters' in general:
            exportkwargs['filters'] = general['filters'].split(',')
        if 'title' in general:
            exportkwargs['title'] = general['title']
        if 'pandoc_args' in general:
            exportkwargs['pandoc_args'] = general['pandoc_args']

    for feed in feeds:
        feed_id = feed.name.split('.')[1]
        urls = feed['url'].split(',')
        collection = Collection(feed_id, urls, feed['name'])
        if feed.get('fetch-original'):
            collection.fetch_original = feed['fetch-original']
        collection.add_title = feed.get('add-title', 'true') == "true"
        if feed.get('last'):
            collection.set_allowed_timedelta(feed['last'])
        elif timedelta is not None:
            collection.set_allowed_timedelta(timedelta)
        newspaper.add_collection(collection)

    newspaper.download_all()
    newspaper.export(args.outputFile, args.output_format, **exportkwargs)


if __name__ == "__main__":
    main()
