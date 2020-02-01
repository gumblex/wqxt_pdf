#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import sys
import time
import json
import sqlite3
import logging
import collections

import jwt
import img2pdf
import imgautocompress

try:
    from httpx import Client as Session
except ImportError:
    from requests import Session

WITH_PDFRW = True

if WITH_PDFRW:
    try:
        from pdfrw import PdfDict, PdfName
    except ImportError:
        PdfDict = img2pdf.MyPdfDict
        PdfName = img2pdf.MyPdfName
        WITH_PDFRW = False
else:
    PdfDict = img2pdf.MyPdfDict
    PdfName = img2pdf.MyPdfName


HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.8,en;q=0.6",
    "User-Agent": "Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0",
}

re_author = re.compile(r'《.+?》\s*(.+?)\s*【')

logging.basicConfig(stream=sys.stderr, format='%(asctime)s [%(levelname)s] %(message)s', level=logging.INFO)


class APIError(ValueError):
    pass


class TryAgain(ValueError):
    pass


def generate_pdf_outline(pdf, contents, parent=None):
    if parent is None:
        parent = PdfDict(indirect=True)
    if not contents:
        return parent
    first = prev = None
    for k, row in enumerate(contents):
        page = pdf.writer.pagearray[int(row['pnum'])-1]
        bookmark = PdfDict(
            Parent=parent,
            Title=row['label'],
            A=PdfDict(
                D=[page, PdfName.Fit],
                S=PdfName.GoTo
            ),
            indirect=True
        )
        children = row.get('children')
        if children:
            bookmark = generate_pdf_outline(pdf, children, bookmark)
        if first:
            bookmark[PdfName.Prev] = prev
            prev[PdfName.Next] = bookmark
        else:
            first = bookmark
        prev = bookmark
    parent[PdfName.Count] = k + 1
    parent[PdfName.First] = first
    parent[PdfName.Last] = prev
    return parent


def pdf_convert(*images, **kwargs):

    _default_kwargs = dict(
        title=None,
        author=None,
        creator=None,
        producer=None,
        creationdate=None,
        moddate=None,
        subject=None,
        keywords=None,
        colorspace=None,
        contents=None,
        nodate=False,
        layout_fun=img2pdf.default_layout_fun,
        viewer_panes=None,
        viewer_initial_page=None,
        viewer_magnification=None,
        viewer_page_layout=None,
        viewer_fit_window=False,
        viewer_center_window=False,
        viewer_fullscreen=False,
        with_pdfrw=True,
        first_frame_only=False,
        allow_oversized=True,
    )
    for kwname, default in _default_kwargs.items():
        if kwname not in kwargs:
            kwargs[kwname] = default

    pdf = img2pdf.pdfdoc(
        "1.3",
        kwargs["title"],
        kwargs["author"],
        kwargs["creator"],
        kwargs["producer"],
        kwargs["creationdate"],
        kwargs["moddate"],
        kwargs["subject"],
        kwargs["keywords"],
        kwargs["nodate"],
        kwargs["viewer_panes"],
        kwargs["viewer_initial_page"],
        kwargs["viewer_magnification"],
        kwargs["viewer_page_layout"],
        kwargs["viewer_fit_window"],
        kwargs["viewer_center_window"],
        kwargs["viewer_fullscreen"],
        kwargs["with_pdfrw"],
    )

    # backwards compatibility with older img2pdf versions where the first
    # argument to the function had to be given as a list
    if len(images) == 1:
        # if only one argument was given and it is a list, expand it
        if isinstance(images[0], (list, tuple)):
            images = images[0]

    if not isinstance(images, (list, tuple)):
        images = [images]

    for img in images:
        # img is allowed to be a path, a binary string representing image data
        # or a file-like object (really anything that implements read())
        try:
            rawdata = img.read()
        except AttributeError:
            if not isinstance(img, (str, bytes)):
                raise TypeError("Neither implements read() nor is str or bytes")
            # the thing doesn't have a read() function, so try if we can treat
            # it as a file name
            try:
                with open(img, "rb") as f:
                    rawdata = f.read()
            except Exception:
                # whatever the exception is (string could contain NUL
                # characters or the path could just not exist) it's not a file
                # name so we now try treating it as raw image content
                rawdata = img

        for (
            color,
            ndpi,
            imgformat,
            imgdata,
            imgwidthpx,
            imgheightpx,
            palette,
            inverted,
            depth,
            rotation,
        ) in img2pdf.read_images(rawdata, kwargs["colorspace"], kwargs["first_frame_only"]):
            pagewidth, pageheight, imgwidthpdf, imgheightpdf = kwargs["layout_fun"](
                imgwidthpx, imgheightpx, ndpi
            )

            userunit = None
            if pagewidth < 3.00 or pageheight < 3.00:
                logging.warning(
                    "pdf width or height is below 3.00 - too " "small for some viewers!"
                )
            elif pagewidth > 14400.0 or pageheight > 14400.0:
                if kwargs["allow_oversized"]:
                    userunit = img2pdf.find_scale(pagewidth, pageheight)
                    pagewidth /= userunit
                    pageheight /= userunit
                    imgwidthpdf /= userunit
                    imgheightpdf /= userunit
                else:
                    raise img2pdf.PdfTooLargeError(
                        "pdf width or height must not exceed 200 inches."
                    )
            # the image is always centered on the page
            imgxpdf = (pagewidth - imgwidthpdf) / 2.0
            imgypdf = (pageheight - imgheightpdf) / 2.0
            pdf.add_imagepage(
                color,
                imgwidthpx,
                imgheightpx,
                imgformat,
                imgdata,
                imgwidthpdf,
                imgheightpdf,
                imgxpdf,
                imgypdf,
                pagewidth,
                pageheight,
                userunit,
                palette,
                inverted,
                depth,
                rotation,
            )

    if kwargs['contents']:
        if pdf.with_pdfrw:
            catalog = pdf.writer.trailer.Root
        else:
            catalog = pdf.writer.catalog
        catalog[PdfName.Outlines] = generate_pdf_outline(pdf, kwargs['contents'])

    if kwargs["outputstream"]:
        pdf.tostream(kwargs["outputstream"])
        return

    return pdf.tostring()


class WQXTDownloader:
    baseurl = 'https://lib-nuanxin.wqxuetang.com/read/pdf/'
    jwt_secret = "g0NnWdSE8qEjdMD8a1aq12qEYphwErKctvfd3IktWHWiOBpVsgkecur38aBRPn2w"
    loading_img = '3f08d2c4b0d8cac7641730c7f27f7263c8687bc67cdf179de6996edb9d8409bf09664e035b56d72c00d0b46d8dca1868a48290f469064efd5ba611958fe614e1'

    def __init__(self, downloadpath='.', db='wqxt.db'):
        self.downloadpath = downloadpath
        self.db = sqlite3.connect(db)
        self.session = Session()
        self.session.headers.update(HEADERS)
        self.init_db()

    def init_db(self):
        cur = self.db.cursor()
        cur.execute('PRAGMA case_sensitive_like=1')
        cur.execute('CREATE TABLE IF NOT EXISTS api_cache ('
            'url TEXT PRIMARY KEY,'
            'updated INTEGER,'
            'value TEXT'
        ')')
        cur.execute('CREATE TABLE IF NOT EXISTS book_img ('
            'bookid INTEGER,'
            'page INTEGER,'
            'updated INTEGER,'
            'data BLOB,'
            'PRIMARY KEY (bookid, page)'
        ')')
        self.db.commit()

    def json_call(self, bookid, url, cache=True):
        cur = self.db.cursor()
        url = url % bookid
        if cache:
            cur.execute('SELECT value FROM api_cache WHERE url=?', (url,))
            res = cur.fetchone()
            if res:
                return json.loads(res[0])
        r = self.session.get(url, headers={
            'referer': self.baseurl + str(bookid),
            'sec-fetch-mode': 'cors',
            'sec-fetch-site': 'same-origin',
            'user': 'bapkg/com.bookask.wqxuetang baver/1.1.1',
        })
        r.raise_for_status()
        result = r.json()
        if result['errcode']:
            name = url.rsplit('/', 1)[-1]
            raise APIError('%s [%s]: %s', name, result['errcode'], result['errmsg'])
        cur.execute('REPLACE INTO api_cache VALUES (?,?,?)', (
            url, int(time.time()), json.dumps(result['data'])))
        self.db.commit()
        return result['data']

    def get_img(self, bookid, page, jwtkey):
        cur = self.db.cursor()
        cur.execute('SELECT data FROM book_img WHERE bookid=? AND page=?',
            (bookid, page))
        res = cur.fetchone()
        if res:
            return res[0]
        cur_time = time.time()
        jwttoken = jwt.encode({
            "p": page,
            "t": int(cur_time*1000),
            "b": str(bookid),
            "w": 1000,
            "k": json.dumps(jwtkey),
            "iat": int(cur_time)
        }, self.jwt_secret, algorithm='HS256').decode('ascii')
        r = self.session.get(
            "https://lib-nuanxin.wqxuetang.com/page/img/%s/%s?k=%s" % (
            bookid, page, jwttoken), headers={
            'referer': self.baseurl + str(bookid),
            'sec-fetch-mode': 'no-cors',
            'sec-fetch-site': 'same-origin',
        })
        r.raise_for_status()
        result = r.content
        if r.headers.get('pragma') != 'catch':
            raise TryAgain()
        cur.execute('REPLACE INTO book_img VALUES (?,?,?,?)', (
            bookid, page, int(cur_time), result))
        self.db.commit()
        return result

    def download_pdf(self, bookid, convertimg=True):
        logging.info('%s: Loading metadata', bookid)
        r = self.session.get(self.baseurl + str(bookid))
        r.raise_for_status()
        metadata = self.json_call(bookid, "https://lib-nuanxin.wqxuetang.com/v1/read/initread?bid=%s")
        title = metadata['name']
        try:
            author = re_author.match(metadata['title']).group(1)
        except Exception:
            author = None
        contents = self.json_call(bookid, "https://lib-nuanxin.wqxuetang.com/v1/book/catatree?bid=%s")
        sizes = self.json_call(bookid, "https://lib-nuanxin.wqxuetang.com/page/size/?bid=%s")
        jwtkey = self.json_call(bookid, "https://lib-nuanxin.wqxuetang.com/v1/read/k?bid=%s")
        page_num = int(metadata['pages'])
        images = [None] * page_num
        tasks = collections.deque(range(1, page_num+1))
        while tasks:
            i = tasks.popleft()
            try:
                img = self.get_img(bookid, i, jwtkey)
                if convertimg:
                    img, imgfmt = imgautocompress.auto_encode(img)
                images[i-1] = img
                logging.info('%s: %s/%s', bookid, i, page_num)
            except TryAgain:
                tasks.append(i)
                logging.info('%s: %s/%s not loaded', bookid, i, page_num)
                time.sleep(0.5)
        logging.info('%s: Generating PDF', bookid)
        with open("%s-%s.pdf" % (bookid, title), "wb") as f:
            pdf_convert(
                images,
                title=metadata['name'],
                author=author,
                with_pdfrw=True,
                contents=contents,
                outputstream=f
            )

if __name__ == '__main__':
    # usage: python3 crawl_wqxt.py <book_id>
    dl = WQXTDownloader()
    dl.download_pdf(int(sys.argv[1]))
