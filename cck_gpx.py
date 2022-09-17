#! /usr/bin/env python3

# Revolting bodge to scrape a delivery round from app.cckitchen.uk, and
# put its route waypoints in a GPX file, for use in a map application.
# Usage:
#   cck_gpx.py saved_app_page.html out.gpx
# saved_app_page.html is a route page that you've previously saved
# from a web browser (in such a way that the modified DOM is saved).
# (Can't fetch URL directly, because of client-side Javascript, hence
# the extra faff.)
# 
# GPX file deliberately does not attempt to include all data you need
# for the route; don't rely on it solely! You'll need to have the
# web app and/or printed route sheet handy too.
# (Because (a) web scraping is inherently unreliable, and some data
# like allergies is safety-critical; (b) to minimise the amount of
# personal data lying around in files.)
#
# Dependencies:
#   pip install openlocationcode  [or hack direct path, see below]
#   pip install gpxpy             [or Debian Linux package "python3-gpxpy"]
#   pip install lxml              [or Debian Linux package "python3-lxml"]

# GPX file should be compatible with any consumer, but was written
# with the OsmAnd map app (https://osmand.net/) in mind.
# Apologies:
# This is ludicrously overcomplicated; the core function could be
# done in maybe 1/4 the space, but I initially thought it might be a
# long-term thing, so wanted to be sure it would never give misleading
# output if the web app changed.
# The error handling is pretty bad.

# Originally written 2022-09.
# 
# Copyright (c) 2022 faceless-stoat
# 
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
# 
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
# REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
# AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
# INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
# LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
# OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
# PERFORMANCE OF THIS SOFTWARE.

import sys
import re
import urllib

# Dealing with plus codes / OLCs:
try:
    # If you are not funny about PyPI like me, you'll have already
    # done "pip install openlocationcode", and this will just work:
    from openlocationcode import openlocationcode as olc
except ImportError:
    # But I'm funny like that, so I run it directly from a git checkout
    # of https://github.com/google/open-location-code :
    import os
    sys.path.append(os.path.expanduser("~")
                    + "/src/open-location-code-git/python")
    from openlocationcode import openlocationcode as olc

# Dealing with GPX file format:
import gpxpy
import gpxpy.gpx

# HTML parsing:
from lxml import html, etree

# HELPER FUNCTIONS

def place_id_from_google_maps_url(url):
    """
    Extract the 'place ID' from a Google Maps '/maps/place/' type URL.
    (Which may be a plus code, or may be one of their proprietary Place IDs
    that we can't do anything with, but that's the caller's problem.)
    Returns None if this didn't look like one of those URLs.
    """
    # TODO:
    #  - could also parse those formats that contain literal lat/long
    #  - could cope with maps.app.goo.gl, assuming it's not entirely
    #    proprietary 'place IDs'

    # Just look at the path, ignore everything else (including hostname).
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path)
    # Have seen URLs with trailing %20
    path = path.rstrip()
    m = re.match('/maps/place/(.*)$', path)
    if m:
        return m.group(1)
    else:
        return None

def firstnameish(fullname):
    """
    Try to turn a full name into a less-unique first name.
    But, if it looks like we have initials, include more of the name, to
    try to avoid ambiguity within the route.
    """
    names = fullname.split()
    if len(names) == 0:
        return None
    elif len(names) == 1:
        # Little choice but to use full name
        return names[0]
    else:
        # Ludicrously overengineered name abbreviation.
        namelist = []
        # Two initials ought to be sufficient to disambiguate
        for index in range(2):
            if index == len(names)-1:
                # Ugh, we've run out of names. As a last-ditch measure,
                # abbreviate the final one, for "F Bloggs" -> "F B."
                namelist.append(names[index][0] + ".")
                break
            namelist.append(names[index])
            if not re.match('[A-Za-z]\.?$', names[index]):
                # Looks like a non-initial. That'll do.
                break
            # Otherwise, keep gathering initials.
        return ' '.join(namelist)

def match_tags(startnode, pattern):
    """
    Helper function that matches the child elements of a node against
    a list of expected XPath expressions (usually just tag names), 
    and returns a nominated subset of them iff a match is found.
    pattern is a list of dicts, each with the following keys:
      'e':    XPath expression child must match (mandatory), e.g. 'p' for <p>
              Must return 0 or 1 matches.
      'bind': name to save matching element to in return dict, if required
      'opt':  True if this element of the pattern is allowed to be absent
              (the implementation of this is very bad, only 1 is allowed)
    If a match is found, a dict is returned, containing any children
    marked as 'bind' using the specified names as keys (if none such, then
    an empty dict is returned).
    If no match is found, None is returned.
    As well as considering taglist, this function considers it a
    non-match iff there are any non-whitespace text children of startnode
    (to guard against ignoring significant text).
    (It ignores children other than elements and text.)
    """
    nodelist = startnode.xpath("*|text()[normalize-space()!='']")
    # If there are any non-element nodes (i.e., text nodes) in nodelist,
    # consider this a non-match.
    if any(not etree.iselement(x) for x in nodelist):
        return None
    # Now we know nodelist contains only elements.

    # XXX: I am too feeble to write a backtracking parser thing that
    # will cope with patterns where an element matches both an optional
    # or mandatory bit of the pattern, and we won't know which is right
    # without looking later in the input.
    # For now, it's sufficient to write an extremely cheesy one-pass
    # matcher that allows exactly one optional pattern element, and
    # looks at list lengths to determine whether to use it.
    pattern_mandatory = \
        [tagd for tagd in pattern if 'opt' not in tagd or tagd['opt']!=True]
    if len(pattern) - len(pattern_mandatory) > 1:
        # Don't currently support >1 optional element
        raise ValueError(">1 optional element in pattern")
    elif len(pattern) - len(pattern_mandatory) == 1:
        # Work out whether to use optional match
        if len(pattern) == len(nodelist)+1:
            # No room for optional one, drop it
            pattern = pattern_mandatory
        elif len(pattern) != len(nodelist):
            # Length doesn't match either with or without optional
            # element, obviously not a match
            return None
        # else, keep pattern as-is including optional element
    # else, no optional elements, keep pattern as-is

    # Now we can do a simple 1:1 match between pattern and nodelist.
    result = {}
    for tagd in pattern:
        # This shouldn't raise IndexError, due to tests above:
        node = nodelist.pop(0)
        matches = node.xpath('self::' + tagd['e'])
        if len(matches) > 1:
            # Getting >1 match means a bad pattern was supplied.
            raise ValueError("Pattern '%s' returned >1 match" % tagd['e'])
        elif len(matches) == 0:
            # No match, so pattern overall doesn't match
            return None
        (match,) = matches  # now we know there was exactly 1
        if 'bind' in tagd:
            result[tagd['bind']] = match
    # If we didn't bail out of above loop, whole pattern matches, so
    # return any results
    return result

# MAIN BODGE

if len(sys.argv) < 2:
    print("usage: cck_gpx.py in.html out.gpx", file=sys.stderr)
    sys.exit(2)

# PARSE THE HTML, and convert pluscodes/OLC to lat/long
# Basic approach: https://docs.python-guide.org/scenarios/scrape/

tree = html.parse(sys.argv[1])

# What https://app.cckitchen.uk/?p=DEMO looked like on 2022-09-03,
# augmented by peeking in components/ in
# https://github.com/Cambridge-Community-Kitchen/cck-deliveries
# (all subject to change without notice, obvs):
# Inside <main> tag:
#   1st <div> with the header "CCK Deliveries"
#   2nd <div> with the content:
#     1. <div> containing:
#        a. a further <div> containing route description
#           "Deliveries for 04/09/2022 in Demo"
#        b. also a <button> "Reset"
#     2. (conjectured) optional <div> containing "dish of the day" info
#     3. <ul> with the actual route points, see below
#     4. <div> with "Back to the Lockon" map link, proprietary place ID
# Inside the <ul> is the list of route points: each is a <li> containing
# a <div>, followed by a <hr>. Inside that <div>:
# 1. <div> containing two <p>: client name, textual plus code
# 2. <p>: textual address description
# 3. <div> containing <span> and <p>: [2] [portions]
# 4. <p> with special instructions
# 5. <p> with allergies
# 6. (optional) <p> with "when not home" instructions
# 7. <div> containing:
#     <a href> Google Maps link
#     (optional) <a href> "Call" (tel:) link
#     <div> spacer
#     <button> to mark done
# (There's no sign in the web app that DEMO is a rigged demo, so it can
# be expected to look the same as real routes, with the above optional
# variations.)

# This idiom, used extensively below, asserts that there's exactly one
# result from the XPath expression (otherwise you get ValueError).
# Here, if there isn't exactly one <main> element, we're in deep trouble,
# so don't bother catching the exception.
(main,) = tree.xpath('//main')

# Find the route points. Obviously essential.
try:
    # Assumes there's only one <ul> anywhere -- might break.
    (ulist,) = main.xpath('.//ul')
except ValueError:
    # The original HTML from the server, before Javascript has got at it,
    # lacks the <ul> element, so give a hint.
    # (Firefox hint works with 91.x ESR at least)
    print("""
Couldn't find route list (exactly one <ul> element), giving up.

(Is this raw server HTML? You need to save it from a web browser, after
it's executed the embedded Javascript to fetch the route data, in such
a way that the browser saves the modified DOM.
In Firefox, "Save Page As..." then "Web Page, complete".)
""", file=sys.stderr)
    raise

routepoints = []

# Route points are <li> directly under <ul>. (There's other guff under
# <ul> like <hr>, which we ignore.)
ulistitems = ulist.xpath('li')
if len(ulistitems) == 0:
    print("Found list, but no route points in it!", file=sys.stderr)
for (index, listitem) in enumerate(ulistitems):
    try:
        # Almost completely gratuitous attempt to understand all the structure.
        # All we actually use out of all this is a name for the waypoint,
        # for easy correlation with route sheet.
        # Mainly all of the rest is to try to make sure our ad-hoc parsing
        # is guessing the right place to find that name.
        l1 = match_tags(listitem, [
            { 'e': 'div',  'bind': 'div1' }         # expect a single <div>
        ])
        # (But, since we're looking in great depth anyway, we may as well
        # gather the fields to help debug, or in case I change my mind
        # about the level of detail.)
        fields = {}
        # Main structure
        l2 = match_tags(l1['div1'], [
            { 'e': 'div',  'bind': 'name_olc_div' },
            { 'e': 'p',    'bind': 'addr_p' },
            { 'e': 'div',  'bind': 'portions_div' },
            { 'e': 'p',    'bind': 'insns_p' },
            { 'e': 'p',    'bind': 'allergies_p' },
            { 'e': 'p',    'bind': 'nothome_p', 'opt': True },
            { 'e': 'div',  'bind': 'links_div' }
        ])
        # Expect <div> containing two <p>: client name and textual OLC
        l3 = match_tags(l2['name_olc_div'], [
            { 'e': 'p',    'bind': 'fullname_p' },
            { 'e': 'p',    'bind': 'olc_p' }
        ])
        fields['fullname'] = l3['fullname_p'].text_content().strip()
        # Use only part of the client's full name in the waypoint name.
        # (FIXME: could defer this to later, and try then to ensure
        # unique waypoint names)
        # (FIXME: do we want to include index in waypoint name too?)
        ptname = firstnameish(fields['fullname'])
        fields['placeid'] = l3['olc_p'].text_content().strip()
        # Could put address in waypoint description, but it could reveal too
        # much personal info.
        # FIXME: a brief summary like 'Carlton Way' or 'Edgecombe' would
        #   be really great, but can eyeball that from paper route sheet
        fields['address'] = l2['addr_p'].text_content().strip()
        # Sanity-check the expected text in this, just to check we're not
        # totally lost:
        # (FIXME: could move this to match_tags(), something like
        #   p[descendant::text()[contains(., "portion")]   (untested)
        portionstext = l2['portions_div'].text_content()
        if not 'portion' in portionstext:
            raise ValueError("Didn't find 'portion' where expected "
                             "(found '%s'); assuming lost" \
                             % (portionstext))
        # (This yields '4portions' which is ugly, we'd be better off parsing
        # tags to get just the numeric part if we actually wanted it:)
        fields['portions'] = portionstext.strip()
        fields['instructions'] = l2['insns_p'].text_content().strip()
        fields['allergies'] = l2['allergies_p'].text_content().strip()
        if 'nothome_p' in l2:
            nothome = l2['nothome_p'].text_content().strip()
            boilerplate = "If no-one's home and you can't make contact: "
            if nothome.startswith(boilerplate):
                nothome = nothome[len(boilerplate):]
            fields['nothome'] = nothome.strip()
        l3 = match_tags(l2['links_div'], [
            { 'e': "a[contains(text(),'Google Maps')]", 'bind': 'maplink_a' },
            { 'e': "a[contains(text(),'Call')]",        'bind': 'tellink_a',
                                                        'opt': True },
            { 'e': "div[not(node())]" },   # spacer with no content
            { 'e': 'button' }
        ])
        fields['mapurl'] = l3['maplink_a'].get('href')
        # Cheeky little plus-code consistency check:
        placeid_from_url = place_id_from_google_maps_url(fields['mapurl'])
        if fields['placeid'] != placeid_from_url:
            raise ValueError("Thought '%s' was the plus code, but it doesn't "
                             "match the map URL ('%s'); assuming lost" \
                             % (fields['placeid'], placeid_from_url))
        # Also check it's a plausible plus code, so we can fall back to
        # cruder method in case we're totally confused
        if not olc.isValid(fields['placeid']):
            raise ValueError("Thought '%s' was the plus code, but it doesn't "
                             "seem valid; assuming lost" % (fields['placeid']))
        placeid = fields['placeid']  # ok, we trust it now
        # Don't barf if the 'Call' link isn't present, it isn't always:
        if 'tellink_a' in l3:
            tellink = l3['tellink_a'].get('href')
            # urllib isn't very reliable at parsing the tel: URIs that we
            # get here; it has particular trouble if the payload is
            # all-numeric (e.g. no spaces), for complicated reasons, see e.g.
            # https://bugs.python.org/issue14072
            # https://bugs.python.org/issue27657
            # Here we gratuitously try anyway, but with a fallback strategy:
            tel_parsed = urllib.parse.urlparse(tellink)
            if tel_parsed.scheme == 'tel':
                fields['telephone'] = urllib.parse.unquote(tel_parsed.path)
            elif tel_parsed.scheme == '' and tellink.startswith('tel:'):
                # This is how urllib fails, so try fallback strategy.
                fields['telephone'] = urllib.parse.unquote(tellink[4:])
            else:
                raise ValueError("Expecting tel: URL, got '%s'; assuming "
                                 "lost" % (tellink))
        #print(fields)
    except (ValueError, KeyError, TypeError) as e:
        # Fallback strategy which is probably good enough: just try to
        # find exactly one Google Maps URL somewhere under the <li>.
        print(e, file=sys.stderr)
        print("Failed to fully understand route point %d (of %d), "
              "falling back to URL-only" % (index+1, len(ulistitems)),
              file=sys.stderr)
        ptname = "Delivery no %d" % (index+1)
        try:
            # FIXME: make Google URL more configurable/tolerant
            (maplink_a,) = \
                listitem.xpath(".//a[contains(@href,'google.com/maps')]")
            placeid = place_id_from_google_maps_url(maplink_a.get('href'))
        except ValueError:
            print("Fallback failed to find map URL for point %d!" \
                  % (index+1), file=sys.stderr)
            placeid = None
    # Now try to convert place ID as a plus code.
    # (TODO: we could recoverNearest() on a non-full plus code if we needed)
    if placeid and olc.isValid(placeid) and olc.isFull(placeid):
        # We _could_ muck around with min/max to derive an 'hdop' figure
        # for the GPX file, but no-one would ever use it.
        (lat, lng) = olc.decode(placeid).latlng()
        routepoints.append({
            'name': ptname,
            'lat':  lat,
            'lng':  lng
        })
    else:
        print("Couldn't parse point %d's place ID '%s' as a full-length "
              "plus code" % (index+1, placeid), file=sys.stderr)

if len(routepoints) != len(ulistitems):
    print("Route incomplete - only understood %d out of %d points!" \
          % (len(routepoints), len(ulistitems)), file=sys.stderr)
if len(routepoints) == 0:
    print("No route points to emit, giving up.", file=sys.stderr)
    sys.exit(1)

# Also try to find the overall route description, but don't stress out
# if we can't.
# (OsmAnd as GPX consumer will ignore it anyway)
try:
    # Could be more paranoid and look for expected content to check we're
    # in roughly the right place ("CCK Deliveries", "Reset" button, etc)
    (_, l1div2,) = main.xpath('div')        # 2nd of 2 <div>s under <main>
    l2 = match_tags(l1div2, [
        { 'e': 'div',  'bind': 'route_reset_div' },
        { 'e': 'div',  'bind': 'dish_div', 'opt': True },
        { 'e': 'ul' },  # route list, already dealt with this
        { 'e': 'div' }  # "Back to <wherever>"
    ])
    (l3div1,) = l2['route_reset_div'].xpath('div')  # the only <div> under that
    route_description = l3div1.text_content()  # smush multiple tags together
    # Normalise whitespace:
    route_description = ' '.join(route_description.split())
    # FIXME: could do something with dish_div (dish-of-the-day) as well
except (ValueError, KeyError):
    print("Couldn't find route description, continuing anyway", file=sys.stderr)
    route_description = None

# WRITE THE GPX

gpx = gpxpy.gpx.GPX()
# (OsmAnd ignores gpx.name and gpx.description in favour of filename,
# but for completeness:)
if route_description:
    gpx.description = route_description

# Naively, GPX's "route" concept seems look a good match, since it
# implies a sequential relationship; but "waypoints" work better in
# OsmAnd's UI at least (can import them as map markers, which have
# the right affordances for this job), and are imported in order.
# So, we're not using "route".
# (For the record, OsmAnd ignores route name/description attributes)
#gpx_route = gpxpy.gpx.GPXRoute(name="gpxroute_name", description="gpxroute_desc")
#gpx.routes.append(gpx_route)

for point in routepoints:
    # OsmAnd: waypoint description attribute is visible in track view,
    # and marker view if you dig into "Details".
    # OsmAnd markers created from waypoints don't have distinct colours
    # by default, unlike markers created in the app (could fix with GPX
    # extension), although OsmAnd does seem to invent colours for menu
    # purposes. Nor is the current marker distinguished on the map view.
    gpx.waypoints.append(gpxpy.gpx.GPXWaypoint(point['lat'], point['lng'],
                                               name=point['name']))
    #gpx_route.points.append(gpxpy.gpx.GPXRoutePoint(stuff)

gpxfile = open(sys.argv[2], 'w', encoding='utf-8')
gpxfile.write(gpx.to_xml())
gpxfile.close()
