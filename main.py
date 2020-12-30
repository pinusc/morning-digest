#!/usr/bin/env python
import feedparser
import urllib.request as request
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

progressbar.streams.wrap_stderr()

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
                <section class=collection id={collectionid}>
                <h1>{name}</h1>
                {articles}
                </section>
                """.format(name=collection.name,
                           collectionid=collection.id,
                           articles=collection.render_html())
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
    def export_pdf(self, filename, cli_args=None):
        args = []
        # args = [
        #     '--pdf-engine=xelatex',
        # ]
        if cli_args.title:
            title = cli_args.title
            args += ['-V', f'title:"{title}"']
        if cli_args.pandoc_args:
            args += cli_args.pandoc_args

        message("Exporting to PDF...")
        pypandoc.convert_text(self.render_html(), 'pdf', 'html',
                              outputfile=filename, extra_args=args)

    @rotatingbar
    def export_otherformat(self, filename, out_format, cli_args=None):
        args = []
        if cli_args.title:
            title = cli_args.title
            args += ['-V', f'title:"{title}"']
        if cli_args.pandoc_args:
            args += cli_args.pandoc_args

        message(f"Exporting to {out_format}...")
        pypandoc.convert_text(self.render_html(), out_format, 'html',
                              outputfile=filename, extra_args=args)


class Collection:
    _deltas = {
        'day': timedelta(days=1),
        'week': timedelta(days=7),
        'month': timedelta(days=30),
    }

    def __init__(self, collection_id, urls, name):
        self.name = name
        self.id = collection_id
        self.urls = urls
        self._articles = []
        self._timedelta = None
        self.fetch_original = False

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
        message("Downloading article texts...")
        bar = progressbar.ProgressBar(marker='=', max_value=len(articles))
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
            self.date = kwargs['date']
        if kwargs.get('full_text'):
            self.full_text = kwargs['full_text']

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

    parser.add_argument('--debug', dest='debug', action='store_true',
                        default=False,
                        help='Print debug info')

    parser.add_argument('--no-toc', dest='toc', action='store_false',
                        default=True,
                        help='Disables table of contents')

    parser.add_argument('--format', dest='output_format', action='store',
                        default='pdf', help='Output format')

    parser.add_argument('pandoc_args', action='store',
                        metavar='-- PANDOC_FLAGS', nargs='*',
                        help='Additional flags to pass to pandoc')

    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.ERROR)

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
        feed_id = feed.name.split('.')[1]
        urls = feed['url'].split(',')
        collection = Collection(feed_id, urls, feed['name'])
        if feed.get('fetch-original'):
            collection.fetch_original = ['fetch-original']
        if feed.get('last'):
            collection.set_allowed_timedelta(feed['last'])
        elif timedelta is not None:
            collection.set_allowed_timedelta(timedelta)
        newspaper.add_collection(collection)

    newspaper.download_all()
    if args.output_format == 'pdf':
        newspaper.export_pdf(args.outputFile, args)
    else:
        newspaper.export_otherformat(args.outputFile, args.output_format, args)


if __name__ == "__main__":
    main()
