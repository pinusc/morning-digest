#!/usr/bin/env python
from panflute import Image, Div, Emph
from panflute import run_filters, debug


def latex_pic(elem, doc):
    if doc.format == 'latex':
        if type(elem) == Image:
            elem.attributes['width'] = '80%'
            elem.attributes['height'] = '60%'
            return elem


def remove_date(elem, doc):
    def has_xkcd_ancestor(elem):
        while elem.parent is not None:
            if type(elem.parent) == Div and elem.parent.identifier == 'xkcd':
                return True
            elem = elem.parent
        return False

    if type(elem) == Emph and type(elem.parent.parent.parent) == Div \
            and has_xkcd_ancestor(elem):
        return []


def main(doc=None):
    return run_filters([latex_pic, remove_date], doc=doc)


if __name__ == "__main__":
    main()
