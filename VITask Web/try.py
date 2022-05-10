# imports
import base64
import random
import os
from PIL import Image, ImageFilter
import json
import firebase_admin
from firebase_admin import credentials, db, storage
import datetime, requests
from bs4 import BeautifulSoup
from uuid import uuid4
from constants import *

cred = credentials.Certificate("firebase.json")
firebase_admin.initialize_app(cred, {
    'databaseURL':'https://vit-app-fd3f1-default-rtdb.firebaseio.com/',
    'storageBucket': 'vit-app-fd3f1.appspot.com',

})

bucket = storage.bucket()

CAPTCHA_DIM = (180, 45)
CHARACTER_DIM = (30, 32)
#Above values were checked from various captchas


def save_captcha(captchasrc, username):
    """
    Downloads and save a random captcha from VTOP website in the path provided
    Defaults to `/captcha`
    num = number of captcha to save
    """
    base64_image = captchasrc[23:]
    # TODO: Change the name of file to a random name to prevent any collision
    blob = bucket.blob(f'captcha/{username}-captcha.png')
    new_token = uuid4()
    metadata  = {"firebaseStorageDownloadTokens": new_token}
    blob.metadata = metadata
    blob.upload_from_string(base64.b64decode(base64_image), content_type='image/png')
    
    
def remove_pixel_noise(img):
    """
    this function removes the one pixel noise in the captcha
    """
    img_width = CAPTCHA_DIM[0]
    img_height = CAPTCHA_DIM[1]

    img_matrix = img.convert('L').load()
    # Remove noise and make image binary
    for y in range(1, img_height - 1):
        for x in range(1, img_width - 1):
            if img_matrix[x, y-1] == 255 and img_matrix[x, y] == 0 and img_matrix[x, y+1] == 255:
                img_matrix[x, y] = 255
            if img_matrix[x-1, y] == 255 and img_matrix[x, y] == 0 and img_matrix[x+1, y] == 255:
                img_matrix[x, y] = 255
            if img_matrix[x, y] != 255 and img_matrix[x, y] != 0:
                img_matrix[x, y] = 255

    return img_matrix

def identify_chars(img,img_matrix):
    """
    This function identifies and returns the captcha
    """

    img_width = CAPTCHA_DIM[0]
    img_height = CAPTCHA_DIM[1]

    char_width = CHARACTER_DIM[0]
    char_height = CHARACTER_DIM[1]

    char_crop_threshold = {'upper': 12, 'lower': 44}

    bitmaps = json.load(open("bitmaps.json"))
    captcha =""

    # loop through individual characters
    for i in range(char_width, img_width + 1, char_width):

        # crop with left, top, right, bottom coordinates
        img_char_matrix = img.crop(
            (i-char_width, char_crop_threshold['upper'], i, char_crop_threshold['lower'])).convert('L').load()

        matches = {}

        for character in bitmaps:
            match_count = 0
            black_count = 0

            lib_char_matrix = bitmaps[character]

            for y in range(0, char_height):
                for x in range(0, char_width):
                    if img_char_matrix[x, y] == lib_char_matrix[y][x] and lib_char_matrix[y][x] == 0:
                        match_count += 1
                    if lib_char_matrix[y][x] == 0:
                        black_count += 1

            perc = float(match_count)/float(black_count)
            matches.update({perc: character[0].upper()})

        try:
            captcha += matches[max(matches.keys())]
        except ValueError:
            captcha += "0"

    return captcha


def solve_captcha(captchasrc,username):
    save_captcha(captchasrc,username)
    url = "https://firebasestorage.googleapis.com/v0/b/vit-app-fd3f1.appspot.com/o/captcha%2F"+username+"-captcha.png?alt=media"
    img = Image.open(requests.get(url, stream=True).raw)
    img_matrix = remove_pixel_noise(img)
    captcha = identify_chars(img,img_matrix)
    return captcha

def generate_session(username, password):
    """
    This function generates a session with VTOP. Solves captcha and returns Session object
    """
    
    sess = requests.Session()
    # VTOP also not secure
    sess.get(VTOP_BASE_URL,headers = HEADERS, verify=True)
    login_html = sess.post(VTOP_LOGIN,headers = HEADERS, verify=True).text
    alt_index = login_html.find('src="data:image/png;base64,')
    alt_text = login_html[alt_index+5:] 
    end_index = alt_text.find('"')
    captcha_src = alt_text[:end_index]
    captcha = solve_captcha(captcha_src, username)
    payload = {
        "uname" : username,
        "passwd" : password,
        "captchaCheck" : captcha
    }
    post_login_html = sess.post(VTOP_DO_LOGIN, data=payload, headers=HEADERS, verify=True).text
    valid = True
    
    try:
        soup = BeautifulSoup(post_login_html, 'lxml')
        code_soup = soup.find_all('div', {"id": "captchaRefresh"})
        username = soup.find('input', {"id": "authorizedIDX"})['value']
    except Exception as e:
        print(e)
        valid = False
    finally:
        if(len(code_soup)!=0):
            valid = False
        return (sess, username, valid)

def parse_profile(profile_html):
    # Parsing logic by Apratim.
    soup = BeautifulSoup(profile_html, 'lxml')
    code_soup = soup.find_all('td', {'style': lambda s: 'background-color: #f2dede;' in s})
    tutorial_code = [i.getText() for i in code_soup]
    code_proctor = soup.find_all('td', {'style': lambda s: 'background-color: #d4d3d3;' in s})
    tutorial_proctor = [i.getText() for i in code_proctor]
    holdname = tutorial_code[1].lower().split(" ")
    tempname = []
    for i in holdname:
        tempname.append(i.capitalize())
    finalname = (" ").join(tempname)
    tutorial_code[1] = finalname
    
    # Generating an API Token
    api_gen = tutorial_code[0]
    api_token = api_gen.encode('ascii')
    temptoken = base64.b64encode(api_token)
    token = temptoken.decode('ascii')

    profile = {
                'name': tutorial_code[1],
                'branch': tutorial_code[19],
                'program': tutorial_code[18],
                'regNo': tutorial_code[15],
                'appNo': tutorial_code[0],
                'school': tutorial_code[20],
                'email': tutorial_code[29],
                'proctorName': tutorial_proctor[92],
                'proctorEmail': tutorial_proctor[97],
                'token': token
            }
    
    return profile

def get_student_profile(sess, username):
    """
    Returns Students Personal Details
    Format is {
        "name: "Name-OF-Student",
        "branch": "Elecronisdnvvjssvkjnvljdf",
        "program" : "BTECH",
        "regno" : "17GHJ9838",
        "appNo" : "983y40983",
        "school" : "School of sjdhjs oshdvojs",
        "email" : "notgonnatypehere@fucku.com",
        "proctorEmail" : "yeahkillhim@nah.com",
        "proctorName' "Good Guy",
    }
    """
    # Payload for Profile page.
    payload = {
        "verifyMenu" : "true",        
        "winImage" : "undefined",
        "authorizedID": username,
        "nocache" : "@(new Date().getTime())"   
    }
    status = True
    profile = {}
    try:
        profile_sess = sess.post(PROFILE, data=payload, headers=HEADERS, verify=True)
        # Check for 200 CODE
        if profile_sess.status_code !=200:
            status = False
    except Exception as e:
        print(e)
        status = False
    finally:
        profile_html = profile_sess.text
        try:
            profile = parse_profile(profile_html)
        except Exception as e:
            print(e)
            status = False

        return (profile, status)
    

sess, username, valid = generate_session("21BCE9853","pntbwyS9Tiw8e@K")
res, status = get_student_profile(sess, username)
print(res)