#!/usr/bin/env python3
"""
PDS4 Collection Generator for NSSDCA

Generates PDS4 Collection inventory files (XML + CSV) by scanning directories
of PDS4 labels and creating versioned collections with modification tracking.

Usage:
    python3 makeCollection.py <directory> [<directory> ...]

Input:
    Directories of PDS4 labels, optionally including existing collection.xml(s)
    and .csv files on which to base new versions

Output:
    For each unique collection (grouped by first 5 LID parts):
    - Collection_<type>_v<X.0>.xml - PDS4 Collection Product label
    - Collection_<type>_v<X.0>.csv - Inventory CSV listing all member LIDVIDs

Version Management:
    - If previous collection exists and content changed: increment version
    - If content unchanged: skip (no new version created)
    - Modification history automatically generated (added/dropped products)

Primary Collections Generated:
    - urn:nasa:pds:system_bundle:product_aip
    - urn:nasa:pds:system_bundle:product_sip_deep_archive

History:
    2021 Jan 29: Created (@author: rchen)
    2021 Feb 11: Added getFilenameroot()
    2021 Mar 18: Added qqCitedescqq, changed getFilenameroot() for ESA/JAXA
    2026 Aug 06: Changed MD5 to SHA-256 for FIPS compliance
    2026 Aug 06: Added duplicate LIDVID handling

Author: rchen
"""

template = '''<?xml version="1.0" encoding="UTF-8"?>
<?xml-model href="https://pds.nasa.gov/pds4/pds/v1/PDS4_PDS_QQschemaVersionQQ.sch"
    schematypens="http://purl.oclc.org/dsdl/schematron"?>
<Product_Collection
    xmlns="http://pds.nasa.gov/pds4/pds/v1"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://pds.nasa.gov/pds4/pds/v1
        https://pds.nasa.gov/pds4/pds/v1/PDS4_PDS_QQschemaVersionQQ.xsd">
    <Identification_Area>
        <logical_identifier>QQlidQQ</logical_identifier>
        <version_id>QQvidQQ</version_id>
        <title>QQtitleQQ</title>
        <information_model_version>QQimVersionQQ</information_model_version>
        <product_class>Product_Collection</product_class>
        <Citation_Information>
            <author_list>PDS Data Design Working Group (DDWG)</author_list>
            <editor_list>PDS Change Control Board (CCB)</editor_list>
            <publication_year>QQyearQQ</publication_year>
            <description>QQcitedescQQ</description>
        </Citation_Information>
        <Modification_History>
            QQmodDetailsQQ</Modification_History>
    </Identification_Area>
    <Reference_List>
        <Internal_Reference>
            <lid_reference>QQbundleLidQQ</lid_reference>
            <reference_type>collection_to_bundle</reference_type>
        </Internal_Reference>
    </Reference_List>
    <Collection>
        <collection_type>QQcollTypeQQ</collection_type>
    </Collection>
    <File_Area_Inventory>
        <File>
            <file_name>QQcsvnameQQ</file_name>
            <creation_date_time>QQdateTimeQQZ</creation_date_time>
            <file_size unit="byte">QQfilesizeQQ</file_size>
            <records>QQnumRecordsQQ</records>
            <checksum>
                <checksum_type>SHA-256</checksum_type>
                <checksum_value>QQchecksumQQ</checksum_value>
            </checksum>
        </File>
        <Inventory>
            <offset unit="byte">0</offset>
            <parsing_standard_id>PDS DSV 1</parsing_standard_id>
            <records>QQnumRecordsQQ</records>
            <record_delimiter>Carriage-Return Line-Feed</record_delimiter>
            <field_delimiter>Comma</field_delimiter>
            <Record_Delimited>
                <fields>2</fields>
                <groups>0</groups>
                <maximum_record_length unit="byte">QQmaxRecLengthQQ</maximum_record_length>
                <Field_Delimited>
                    <name>Member Status</name>
                    <field_number>1</field_number>
                    <data_type>ASCII_String</data_type>
                    <maximum_field_length unit="byte">1</maximum_field_length>
                    <field_format>%1s</field_format>
                    <description>Member Status of the files in the collection.</description>
                </Field_Delimited>                
                <Field_Delimited>
                    <name>LIDVID_LID</name>
                    <field_number>2</field_number>
                    <data_type>ASCII_LIDVID_LID</data_type>
                    <maximum_field_length unit="byte">255</maximum_field_length>
                    <field_format>%-255s</field_format>
                    <description>LIDVIDs of the files.</description>
                </Field_Delimited>
            </Record_Delimited>
            <reference_type>inventory_has_member_product</reference_type>
        </Inventory>
    </File_Area_Inventory>
</Product_Collection>
'''
import datetime
qqSchemaVersionqq = "1F00"
qqIMVersionqq     = "1.15.0.0"
currentTime = datetime.datetime.now()
qqDateqq = currentTime.strftime("%Y-%m-%d")
qqDateTimeqq = qqDateqq + 'T' + currentTime.strftime("%H:%M:%S")
qqYearqq = currentTime.strftime("%Y")

#`create a hash of collectionLID to title. If collectionLID not there,
#`throw a warning and use default algorithm of replacing _ and : with ' '

import string, sys, re, getopt
import os	# rename file
import xml.etree.ElementTree as ET
import re
#pds2only import StringIO

# output file name is based on LID

def usage():
    print("usage: ", sys.argv[0], "[-ho:] <fileOrDirectory>[...]")
    print("  -h this help")
    print("  -o output file directory. NOT IMPLEMENTED YET. WANTED???")
    print("Create collection_<collID>*, 1 pair per unique collection LID.")
    sys.exit()

try:
    opts, args = getopt.getopt(sys.argv[1:], "ho:", ["help", "outDir"])
except getopt.GetoptError as err:
    print(err)	#will print something like "option -a not recognized"
    usage()
for o, a in opts:
    if o in ("-h", "--help"):    usage()
    elif o in ("-o", "--outDir"): outDir = a
    else: assert False, "unhandled option"
if len(args) < 1:
    usage()



# return list of all xml files in path
def flattenPaths(path):
    toReturn = []
    if (os.path.isdir(path)):
        for inFile in os.listdir(path):
            x = flattenPaths(path + "/" + inFile)
            if x: toReturn.extend(x)
    elif re.search(r"\.xml$", path):
        toReturn.append(path)
	# else: 
    return toReturn



def remove_namespace(etree, namespace):	#ET handles namespaces verbosely
    """ Takes a parsed ET structure and removes namespace in-place
        from https://stackoverflow.com/questions/18159221/remove-namespace-and-prefix-from-xml-in-python-using-lxml
    """
    ns = u'{%s}' % namespace
    nsl = len(ns)
    for elem in list(etree.iter()):
        if elem.tag.startswith(ns):
            elem.tag = elem.tag[nsl:]

def readXmlFile(inFile):
    tree = ET.parse(inFile)
    doc = tree.getroot()
    remove_namespace(doc,"http://pds.nasa.gov/pds4/pds/v1")
    my_namespaces = dict([
        node for _, node in ET.iterparse(
            inFile, events=['start-ns']
        )
    ])
    return doc



# the PDS Search Results page gets info from <title> and <description>
# <collection_type> also depends on LID
cLid2titleDescType = {
    'urn:nasa:pds:context:agency': [
        'urn:nasa:pds:context:agency:* context products',
        'The PDS4 Context Products for Agencies, e.g. NASA, ESA',
        'Context'],
    'urn:nasa:pds:context:airborne': [
        'urn:nasa:pds:context:airborne:* context products',
        'The PDS4 Context Products for Airborne, e.g. balloon.bopps',
        'Context'],
    'urn:nasa:pds:context:facility': [
        'urn:nasa:pds:context:facility:* context products',
        'The PDS4 Context Products for Facilities, e.g. Keck Observatory, A. Hofmeister Laboratory',
        'Context'],
    'urn:esa:psa:context:instrument_host': [
        'urn:ESA:PSA:context:instrument_host:* context products',
        'The PDS4 Context Products for ESA instrument hosts, e.g. Rosetta spacecraft, Mars Express',
        'Context'],
    'urn:esa:psa:context:instrument': [
        'urn:ESA:PSA:context:instrument:* context products',
        'The PDS4 Context Products for ESA instruments, e.g. Rosetta ROSINA, Mars Express cameras',
        'Context'],
    'urn:esa:psa:context:investigation': [
        'urn:ESA:PSA:context:investigation:* context products',
        'The PDS4 Context Products for ESA investigations, e.g. International Rosetta Mission, Mars Express mission',
        'Context'],
    'urn:nasa:pds:context:instrument_host': [
        'urn:nasa:pds:context:instrument_host:* context products',
        'The PDS4 Context Products for Instrument Hosts, e.g. InSight spacecraft, Mars2020 spacecraft',
        'Context'],
    'urn:nasa:pds:context:instrument': [
        'urn:nasa:pds:context:instrument:* context products',
        "The PDS4 Context Products for Instruments, e.g. Mars2020 MOXIE, MMT's CCD47 Camera",
        'Context'],
    'urn:nasa:pds:context:investigation': [
        'urn:nasa:pds:context:investigation:* context products',
        'The PDS4 Context Products for Investigations, e.g. Mars2020 mission, IRTF observing campaign',
        'Context'],
    'urn:nasa:pds:context:node': [
        'urn:nasa:pds:context:node:* context products',
        'The PDS4 Context Products for Nodes, e.g. EN, GEO',
        'Context'],
    'urn:nasa:pds:context:personnel': [
        'urn:nasa:pds:context:personnel-affiliate:* context products',
        'The PDS4 Context Products for Personnel',
        'Context'],
    'urn:nasa:pds:context:resource': [
        'urn:nasa:pds:context:resource:* context products',
        'The PDS4 Context Products for Resources e.g. MAVEN archive information page',
        'Context'],
    'urn:nasa:pds:context:target': [
        'urn:nasa:pds:context:target:* context products',
        'The PDS4 Context Products for Targets, e.g. planet Mars, asteroid 101955 Bennu',
        'Context'],
    'urn:nasa:pds:context:telescope': [
        'urn:nasa:pds:context:telescope:* context products',
        'The PDS4 Context Products for Telescopes, e.g. MMT 6.5m single-mirror, Keck 10m',
        'Context'],
    'urn:nasa:pds:system_bundle:product_sip_deep_archive': [
        'collection Product SIP Deep Archive in System Bundle',
        'collection Product SIP Deep Archive in System Bundle',
        'Miscellaneous'],
    'urn:nasa:pds:system_bundle:product_aip': [
        'collection Product AIP in System Bundle',
        'collection Product AIP in System Bundle',
        'Miscellaneous'],
    'urn:nasa:pds:misc:document_misc': [
        'Miscellaneous PDS documents',
        'Miscellaneous documents for PDS not in the System Bundle',
        'Document']
}
# given a list of the first 5 parts of a LID, return
# [<title>, <description>, <collection_type>] from cLid2titleDescType[]
# if there; else make up something
def collectionLid2titleDescType(lidParts):
    first5partsOfLid = ":".join(lidParts)
    if first5partsOfLid in cLid2titleDescType: return cLid2titleDescType[first5partsOfLid]
    sys.stderr.write("INFO: new collection " +first5partsOfLid+ "? Add to cLid2titleDescType{} for better <title>, <description>, and/or <collection_type>)\n")
    partBundle = re.sub(r'_', ' ', lidParts[3]).title()  # replace _ with space
    partColl   = re.sub(r'_', ' ', lidParts[4]).title()  #   and use title case
    defaultTitle = "collection " +partColl+ " in bundle " +partBundle
    if lidParts[1] != 'nasa':
        defaultTitle = defaultTitle + ' for ' + lidParts[1].upper() + '/' + lidParts[2].upper()
    return [defaultTitle, defaultTitle, 'Miscellaneous']

def sortbyfield(parent, field):
    parent[:] = sorted(
        parent,
        key=lambda child: float(child.find(field).text),
        reverse = True)

# P1: "Collection_instrument" or "Collection_instrument_host" or ...
# P2: "nasa" or "esa" or "jaxa"
# P3: "1.0"
# P4: (".xml", ".csv") to check for duplicates
# Usually ret = P1+_v+P3. If P2 != nasa, P1+_+P2+_v+P3
# Then if ret + any in the suffix list exists,
# append a letter (incrementing) to ret until no such file exists
import os
def getFilenameroot(coll_lid5, lid2, version, suffixList):
    unique = True
    ret = "_v" + version
    if lid2 == 'nasa': ret = coll_lid5 + ret
    else: ret = coll_lid5 + "_" + lid2 + ret
    for suffix in suffixList:
        if os.path.exists(ret + suffix):  # if any conflicts at all
            unique = False
            break
    if unique: return ret  # if no conflicts, exit
    i = -1
    while not unique:
        unique = True
        i += 1
        for suffix in suffixList:
            if os.path.exists("%s%s%s" % (ret, (chr(ord('a')+i)), suffix)):
                unique = False
                break
    return(ret + chr(ord('a')+i))

# given a dict of lidvids and output filename, return a list of
#   filesize, numrecords, checksum, maxrecordlength
import hashlib
def makeCsv(lidvids, outfilename): #lidvids[lidvid]==filename. Value is useless
    filesize = 0
    maxlen = 0
    f = open(outfilename, "w+")
    for lidvid in sorted(lidvids.keys()):
        line = "P," + lidvid + "\r\n"
        f.write(line)
        filesize += len(line)
        if maxlen < len(line): maxlen = len(line)
    f.close()
    # Use SHA-256 instead of MD5 for FIPS compliance
    sha256_returned = hashlib.sha256(open(outfilename,'rb').read()).hexdigest()
    return [str(filesize), str(len(lidvids.keys())), sha256_returned, str(maxlen)]

# given [highestVID,rootOfElementTree], return [vid,textforQQmodDetailsQQ]
# Using newlidvids, if collection is unchanged, return [highestVID, None]
def getModHistory(viddirdoc, newlidvids):
    xpathMod = "Identification_Area/Modification_History/Modification_Detail"
    xpathFile = "File_Area_Inventory/File/file_name"
    ret = '''<Modification_Detail>
                <modification_date>QQdateQQ</modification_date>
                <version_id>QQvidQQ</version_id>
                <description>QQdescQQ</description>
            </Modification_Detail>
'''
    if viddirdoc is None:
        ret = re.sub(r'QQdescQQ', "Initial version", ret)
        return ["1.0", ret]	# QQdateQQ,QQvidQQ get replaced later
    #else:  #NOTE Modification_History may be blank, so initially use vid
    [vid, dir, doc] = viddirdoc
    oldfile = dir +"/"+ doc.find(xpathFile).text
    with open(oldfile) as f:	# fix needed: carry on if open() fails
        oldlidvids = f.readlines()
    oldlidvids = [x.strip() for x in oldlidvids]	#strip(" PS,") left \n
    newlidvids = ["P," + x for x in newlidvids]
    added = sorted(set(newlidvids) - set(oldlidvids))
    dropped = sorted(set(oldlidvids) - set(newlidvids))
    if (len(added) == 0) and (len(dropped)==0): return [vid, None]
    desc = ""
    if (len(added) > 0): desc += "\nadded:\n  " + "\n  ".join(added)
    if (len(dropped) > 0): desc += "\ndropped:\n  " + "\n  ".join(dropped)
    ret = re.sub(r'QQdescQQ', desc, ret)
    moddetails = doc.findall(xpathMod)
    if not moddetails: modvid = vid
    else:
        sortbyfield(moddetails, "version_id")	# sort in place
        modvid = moddetails[0].find("version_id").text	#[0] is the biggest
    for moddetail in moddetails:
        ret = ret + ET.tostring(moddetail,encoding='unicode')
    if float(vid) > float(modvid): modvid = vid
    # Return version in X.0 format per PDS4 standard
    return [str(int(float(modvid)) + 1) + ".0", ret]

xpathProductClass = "Identification_Area/product_class"
xpathLID = "Identification_Area/logical_identifier"
xpathVID = "Identification_Area/version_id"
import xml.dom.minidom

def choose_newer_file(file1, file2):
    """
    When duplicate LIDVIDs are found, choose which file to keep.
    Prefers: 1) Higher version in filename (e.g., v2.0 over v1.0)
             2) More recent modification time
    Returns: (kept_file, reason_string)
    """
    # Try to extract version from filename (e.g., "..._aip_v2.0.xml" -> 2.0)
    version_pattern = r'_v(\d+\.?\d*)\.xml$'
    match1 = re.search(version_pattern, file1)
    match2 = re.search(version_pattern, file2)

    if match1 and match2:
        ver1 = float(match1.group(1))
        ver2 = float(match2.group(1))
        if ver1 != ver2:
            if ver1 > ver2:
                return (file1, f"filename version {ver1} > {ver2}")
            else:
                return (file2, f"filename version {ver2} > {ver1}")

    # Fall back to modification time
    mtime1 = os.path.getmtime(file1)
    mtime2 = os.path.getmtime(file2)

    if mtime1 > mtime2:
        return (file1, "more recent modification time")
    else:
        return (file2, "more recent modification time")

if __name__ == "__main__":
    newColls = {}	# newColls[u:n:p:c:xxx][u:n:p:c:xxx:yyy::vid] = somefile
    oldColls = {}	# oldColls[u:n:p:c:xxx] = [highvid,dir,eTreeRoot]
    files = []
    for arg in args: files.extend(flattenPaths(arg))	# not append()
    for file in files:
        doc = readXmlFile(file)
        vClass = doc.find(xpathProductClass)
        vLID = doc.find(xpathLID)
        vVID = doc.find(xpathVID)	#NOTE Mod_History is optional
        if vClass is None or vLID is None or vVID is None:
            sys.stderr.write("INFO: File " +file+ " has no product_class or no LID or no VID\n")
            continue
        valueClass = vClass.text
        valueLID = vLID.text
        valueVID = vVID.text	#NOTE Mod_History is optional
        lidParts = re.split(':', valueLID)
        lidvid = valueLID + "::" + valueVID
        if lidParts.__len__() == 6:
            collLid = ":".join(lidParts[0:5])
            if not collLid in newColls: newColls[collLid] = {}
            if lidvid in newColls[collLid]:
                # Duplicate LIDVID found - choose which file to keep
                existing_file = newColls[collLid][lidvid]
                kept_file, reason = choose_newer_file(existing_file, file)
                dropped_file = file if kept_file == existing_file else existing_file
                sys.stderr.write("WARNING: Duplicate LIDVID %s found in:\n" % lidvid)
                sys.stderr.write("  KEPT: %s (%s)\n" % (kept_file, reason))
                sys.stderr.write("  DROPPED: %s\n" % dropped_file)
                newColls[collLid][lidvid] = kept_file
            else:
                newColls[collLid][lidvid] = file
        elif lidParts.__len__() == 5:	#check valueClass==Product_Collection?
            if not valueLID in oldColls or float(oldColls[valueLID][0]) < float(valueVID):
                oldColls[valueLID] = [valueVID, os.path.dirname(file), doc]
        else: sys.stderr.write("INFO: skip file " +file+"\n")	#bundle|badLID
    for collLid in newColls:
        if collLid in oldColls:
            [qqVidqq,qqModDetailsqq] = getModHistory(oldColls[collLid], newColls[collLid].keys())
            if qqModDetailsqq is None:
                sys.stderr.write("INFO: %s::%s unchanged. Skipping\n" % (collLid,qqVidqq))
                continue
        else: [qqVidqq, qqModDetailsqq] = getModHistory(None,None)
        lidParts = re.split(':', collLid)
        filenameRoot = getFilenameroot("Collection_"+lidParts[4], lidParts[1], qqVidqq, (".csv",".xml"))  # returns a unique name. Race condition possible
        qqCsvNameqq = filenameRoot + ".csv"
        sys.stderr.write("INFO: creating " + qqCsvNameqq + " and its label\n")
        [qqFileSizeqq,qqNumRecordsqq,qqChecksumqq,qqMaxRecLengthqq] = makeCsv(newColls[collLid], qqCsvNameqq)
        [qqTitleqq, qqCitedescqq, qqCollTypeqq] = collectionLid2titleDescType(lidParts[0:5])  # somehow this passes 5 parts
        os.chmod(qqCsvNameqq, 0o664)
        qqBundleLidqq = ":".join(lidParts[0:4])
        if lidParts[3] == 'context': qqBundleLidqq = 'urn:nasa:pds:context'  #for now, that bundle has all context collections
        t2 = re.sub(r'QQschemaVersionQQ', qqSchemaVersionqq, template)
        t2 = re.sub(r'QQimVersionQQ',     qqIMVersionqq,     t2)
        t2 = re.sub(r'QQyearQQ',          qqYearqq,          t2)
        t2 = re.sub(r'QQdateTimeQQ',      qqDateTimeqq,      t2)
        t2 = re.sub(r'QQmodDetailsQQ',    qqModDetailsqq,    t2) #has QQdateQQ
        t2 = re.sub(r'QQdateQQ',          qqDateqq,          t2)
        t2 = re.sub(r'QQlidQQ',           collLid,           t2)
        t2 = re.sub(r'QQvidQQ',           qqVidqq,           t2)
        t2 = re.sub(r'QQbundleLidQQ',     qqBundleLidqq,     t2)
        t2 = re.sub(r'QQtitleQQ',         qqTitleqq,         t2)
        t2 = re.sub(r'QQcitedescQQ',      qqCitedescqq,      t2)
        t2 = re.sub(r'QQcollTypeQQ',      qqCollTypeqq,      t2)
        t2 = re.sub(r'QQcsvnameQQ',       qqCsvNameqq,       t2)
        t2 = re.sub(r'QQfilesizeQQ',      qqFileSizeqq,      t2)
        t2 = re.sub(r'QQnumRecordsQQ',    qqNumRecordsqq,    t2)
        t2 = re.sub(r'QQchecksumQQ',      qqChecksumqq,      t2)
        t2 = re.sub(r'QQmaxRecLengthQQ',  qqMaxRecLengthqq,  t2)
        t2 = re.sub(r'>\s*<', '><', t2)	# drop spaces between elements for prettify
        t3 = xml.dom.minidom.parseString(t2)	# prettify xml output
        f = open(filenameRoot + ".xml", "w+")
        f.write(t3.toprettyxml(indent="    "))
        f.close()
    sys.exit()
