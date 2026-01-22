#!/usr/bin/env python3
"""
PUMC Course Select

北京协和医学院研究生选课脚本
"""

import re
import cv2
import sys
import time
import random
import numexpr
import requests
import pytesseract
import numpy as np
from PIL import Image
from io import BytesIO
from datetime import datetime

# Configuration
BASE_URL = 'https://graduatexk.pumc.edu.cn/graduate'

LOGIN_URL = f'{BASE_URL}/index.do'
CAPTCHA_URL = f'{BASE_URL}/getCaptcha.do'
BULLETIN_URL = f'{BASE_URL}/listMyBulletined.do'
LOGIN_SUBMIT_URL = f'{BASE_URL}/j_acegi_security_check'
LOGOUT_URL = f'{BASE_URL}/sso/sso_logout.jsp'
ELECT_COURSE_URL = f'{BASE_URL}/stuelectcourse/addScoreFromPlan.do'

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0 Safari/537.36'
}


def when() -> str:
    """Return current time in HH:MM:SS format."""
    return datetime.now().strftime('%H:%M:%S')


def solve_captcha(s: requests.Session, debug: bool = False) -> int:
    """
    Solve the captcha using OCR.
    
    Args:
        s: Requests session
        debug: If True, print debug information
        
    Returns:
        The solved captcha value, or 0 if failed
    """
    try:
        captcha = s.get(CAPTCHA_URL)
    
        if debug:
            img = Image.open(BytesIO(captcha.content))
            print(f'Captcha image size: {img.size}')
    
        np_array = np.frombuffer(captcha.content, dtype=np.uint8)
        cv2_image = cv2.imdecode(np_array, cv2.IMREAD_COLOR)
        cv2_image_crop = cv2_image[:, :72]
        
        gray = cv2.cvtColor(cv2_image_crop, cv2.COLOR_BGR2GRAY)
        gray_thr = cv2.adaptiveThreshold(
            gray, 255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY_INV,
            15, 4
        )
        img = cv2.bitwise_not(gray_thr)
    
        if debug:
            print('Processed captcha image')
    
        text = pytesseract.image_to_string(
            img,
            config="--psm 7 -c tessedit_char_whitelist=0123456789+-"
        )
        if debug:
            print(f'OCR result: {text.strip()}')
        expr = re.findall(r"[0-9]+[4+\-][0-9]+", text)
        expr = expr[0]
        if debug:
            print(f'Regex result: {expr}')
        
        # "+" is very likely to be recognized as "4"
        if expr[int(len(expr) / 2)] == '4':
            expr = expr[:int(len(expr) / 2)] + '+' + expr[int(len(expr) / 2) + 1:]
        elif len(expr) % 2 == 0 and expr[int(len(expr) / 2) + 1] == '4':
            expr = expr[:int(len(expr) / 2) + 1] + '+' + expr[int(len(expr) / 2) + 2:]
    
        if debug:
            print(f'Final formula: {expr}')
        captcha_value = int(numexpr.evaluate(expr))
        assert captcha_value > 0
        return captcha_value
    except IndexError:
        print('OCR error?')
        return 0
    except AssertionError:
        print('OCR error!')
        return 0
    except SyntaxError:
        print('OCR error!')
        return 0
    except Exception as e:
        if debug:
            print(f'Unexpected error: {e}')
        return 0


def check_login_status(s: requests.Session) -> bool:
    """
    Check if the session is logged in.
    
    Args:
        s: Requests session
        
    Returns:
        True if logged in, False otherwise
    """
    bulletin = s.get(BULLETIN_URL)
    return bulletin.status_code == 200 and 'classicLook0' in bulletin.text


def extract_token(login_text: str) -> str:
    """
    Extract the token from the login page HTML.
    
    Args:
        login_text: HTML content of the login page
        
    Returns:
        The token string
    """
    token_start_pattern = '<input type="hidden" name="token" value="'
    token_start = login_text.find(token_start_pattern)
    token_end = login_text.find('"/>', token_start)
    return login_text[token_start + len(token_start_pattern):token_end]


def login(s: requests.Session, username: str, password_sm3: str, debug: bool = False) -> bool:
    """
    Login to the system.
    
    Args:
        s: Requests session
        username: Username
        password_sm3: SM3 hashed password
        debug: If True, print debug information
        
    Returns:
        True if login successful, False otherwise
    """
    if check_login_status(s):
        if debug:
            print('Already logged in')
        return True
    
    # Get login page and extract token
    login_response = s.get(LOGIN_URL)
    token = extract_token(login_response.text)
    
    if debug:
        print(f'Extracted token: {token}')
    
    # Try to login with captcha solving
    max_attempts = 10
    for attempt in range(max_attempts):
        if debug:
            print(f'Login attempt {attempt + 1}/{max_attempts}')
        
        time.sleep(1 + random.random())
        
        captcha_value = solve_captcha(s, debug=debug)
        if captcha_value == 0:
            if debug:
                print('Failed to solve captcha, retrying...')
            continue
        
        payload = {
            'token': token,
            'j_username': username,
            'j_password': password_sm3,
            'j_captcha': captcha_value,
            'groupId': ''
        }
        
        s.post(LOGIN_SUBMIT_URL, data=payload)
        
        if check_login_status(s):
            if debug:
                print('Login successful!')
            return True
        
        if debug:
            print('Login failed, retrying...')
    
    if debug:
        print('Login failed after maximum attempts')
    return False


def select_course(s: requests.Session, course_id: str) -> str:
    """
    Attempt to select a course.
    
    Args:
        s: Requests session
        course_id: Course task ID
        
    Returns:
        Response text from the server
    """
    response = s.get(ELECT_COURSE_URL, params={'taskid': course_id})
    return response.text


def logout(s: requests.Session) -> None:
    """Logout from the system."""
    s.get(LOGOUT_URL)


def main():
    """Main function."""
    # Configuration - modify these values
    USERNAME = 'username'
    PASSWORD_SM3 = '08594e140bcc046e345325435218f67a85c38c63de6443b197b544d70ee62f26'
    COURSE_IDS = ['114514']  # Add your course IDs here
    
    # Create session
    session = requests.Session()
    session.headers.update(HEADERS)
    
    print('PUMC Course Select Script')
    print('=' * 50)
    
    # Login
    print('\nStep 1: Logging in...')
    if not login(session, USERNAME, PASSWORD_SM3, debug=True):
        print('Failed to login. Exiting.')
        return
    
    print('\nStep 2: Starting course selection loop...')
    print('Press Ctrl+C to stop\n')
    
    try:
        # Main selection loop
        result = select_course(session, COURSE_IDS[0])
        
        while '超过课容量' in result:
            for course_id in COURSE_IDS:
                response = session.get(ELECT_COURSE_URL, params={'taskid': course_id})
                result = response.text
                sys.stdout.write('\r' + when() + '\t' + result.replace('\n', ''))
                sys.stdout.flush()
                time.sleep(5 + 5 * random.random())
        
        print('\n\nCourse selected successfully!')
        print(f'Result: {result}')
        
    except KeyboardInterrupt:
        print('\n\nInterrupted by user')
    finally:
        # Optional logout
        print('\nLogging out...')
        logout(session)
        if not check_login_status(session):
            print('Logged out successfully')


if __name__ == '__main__':
    main()
