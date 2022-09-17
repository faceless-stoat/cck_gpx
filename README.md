# cck_gpx.py

`cck_gpx.py` is a special-purpose Python script for
[Cambridge Community Kitchen](https://cckitchen.uk/) delivery
volunteers. It reads a delivery route from the current (2022-09)
web app, and copies its delivery stops into waypoints in a
[GPX file](https://en.wikipedia.org/wiki/GPS_Exchange_Format),
which some people may find more convenient to use with mapping
applications, etc.

This is hopefully a short-term stop-gap until the web app can produce
GPX files natively.

The script works by parsing the HTML source of the web page, and
guessing which bits are the relevant data, without any assistance from
the web app. This is an awful fragile bodge, and could break at any
time. `cck_gpx.py` is therefore quite paranoid when looking at the
structure of the web page, with a fallback strategy to try to produce
*some* useful output even when it thinks it is confused.

## Prerequisites

`cck_gpx.py` is a standalone [Python](https://www.python.org/) (3) script.
You can just download that one file if you like; nothing else in this
git repository is needed for it to run.

It depends on a few packages outside the Python standard library,
which you'll need to make available. They can all be installed with
`pip`:

    pip install openlocationcode
    pip install gpxpy
    pip install lxml

`cck_gpx.py` ought to work on any platform that can run Python,
although it was originally written and tested on Linux.

## Usage

1. Just before a delivery shift, you'll have been sent a link to the
web app; open that in a web browser, and wait for route information
to be displayed.
(To test the script, you can use <https://app.cckitchen.uk/?p=DEMO>.)
2. Save the web page to a `.html` file (see below).
3. Run this script, with arguments being the HTML you just saved and
the name of the GPX file to create:
`python3 cck_gpx.py saved.html route.gpx`

Three possible outcomes:
- Script says nothing and produces a GPX file: all is good.
- Script kvetches a bit, but still produces a GPX file. Read the
warnings - GPX file may not have good labels, or less likely, may be
missing some waypoints, but should still have *some* useful info.
Proceed with caution.
- Script complains, and doesn't produce a GPX file at all.

If a `.gpx` file was produced, you can then load it into your tool of
choice.

**Do not rely solely on the GPX file when delivering!** It
deliberately doesn't try to include all the information you'll need;
keep the web app and/or printed route sheet to hand too. (And please
delete all copies of the GPX file when you're done with the route,
since it contains personal information.)

## Obtaining the HTML input

**You must save the HTML from a web browser**, in a specific way.

- _Firefox_: right-click on page; select "Save Page As..."; in the
file selector, make sure that "Web Page, complete" is selected;
choose a path/filename and click "Save".
(This will create a `_files` directory as well as a `.html` file, but
`cck_gpx.py` only needs the latter.)

- _Chrome_ and derived browsers: _FIXME_ I haven't tried this, and I
don't know if there's a straightforward way to save the modified DOM;
I'm seeing hints online that maybe not, so maybe you have to muck
around with "Copy HTML" in dev tools, or use a browser extension? What
a faff if so, sorry.

If you haven't managed to save the HTML in the right kind of way, the
script will tell you and produce no output.

(Why this faff: the current web app uses client-side Javascript to
fetch the actual route data and populate the DOM with it, and the
script needs to see that copy. So this script can't just fetch
directly from the network, since nothing would execute the Javascript
in that case.)
