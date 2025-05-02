import contextlib
import logging

from pyotp import TOTP
from selenium.common import TimeoutException
from selenium.common.exceptions import (
    ElementNotInteractableException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By
from undetected_chromedriver import Chrome

from src.browser import Browser
from src.utils import CONFIG, APPRISE


class LoginError(Exception):
    """
    Custom exception for login errors.
    """


class Login:
    """
    Class to handle login to MS Rewards.
    """
    browser: Browser
    webdriver: Chrome

    def __init__(self, browser: Browser):
        self.browser = browser
        self.webdriver = browser.webdriver
        self.utils = browser.utils

    def check_locked_user(self):
        try:
            element = self.webdriver.find_element(
                By.XPATH, "//div[@id='serviceAbuseLandingTitle']"
            )
            self.locked(element)
        except NoSuchElementException:
            pass

    def check_banned_user(self):
        try:
            element = self.webdriver.find_element(By.XPATH, '//*[@id="fraudErrorBody"]')
            self.banned(element)
        except NoSuchElementException:
            pass

    def locked(self, element):
        try:
            if element.is_displayed():
                logging.critical("This Account is Locked!")
                self.webdriver.close()
                raise LoginError("Account locked, moving to the next account.")
        except (ElementNotInteractableException, NoSuchElementException):
            pass

    def banned(self, element):
        try:
            if element.is_displayed():
                logging.critical("This Account is Banned!")
                self.webdriver.close()
                raise LoginError("Account banned, moving to the next account.")
        except (ElementNotInteractableException, NoSuchElementException):
            pass

    def login(self) -> None:
        try:
            if self.utils.isLoggedIn():
                logging.info("[LOGIN] Already logged-in")
                self.check_locked_user()
                self.check_banned_user()
            else:
                logging.info("[LOGIN] Logging-in...")
                self.execute_login()
                logging.info("[LOGIN] Logged-in successfully!")
                self.check_locked_user()
                self.check_banned_user()
            assert self.utils.isLoggedIn()
        except Exception as e:
            logging.error(f"Error during login: {e}")
            if CONFIG.browser.visible:
                print("[LOGIN] Manual fallback mode: Log in manually in the opened browser window.")
                input("[LOGIN] Press Enter when you're at the Rewards homepage...")
            else:
                self.webdriver.close()
                raise

    def execute_login(self) -> None:
        try:
            emailField = self.utils.waitUntilVisible(By.ID, "i0116", timeToWait=30)
            logging.info("[LOGIN] Entering email...")
            emailField.click()
            emailField.send_keys(self.browser.email)
            assert emailField.get_attribute("value") == self.browser.email
            self.utils.waitUntilClickable(By.ID, "idSIButton9").click()
        except TimeoutException:
            raise LoginError("Email field not visible. Login screen may have changed.")

        isPasswordless = False
        with contextlib.suppress(TimeoutException):
            self.utils.waitUntilVisible(By.ID, "displaySign")
            isPasswordless = True
        logging.debug("isPasswordless = %s", isPasswordless)

        if isPasswordless:
            codeField = self.utils.waitUntilVisible(By.ID, "displaySign")
            logging.warning(
                "[LOGIN] Confirm your login with code %s on your phone (you have one minute)!\a",
                codeField.text,
            )
            if CONFIG.get("apprise.notify.login-code"):
                APPRISE.notify(
                    f"Code: {codeField.text} (expires in 1 minute)",
                    "Confirm your login on your phone",
                )
            self.utils.waitUntilVisible(By.NAME, "kmsiForm", 60)
            logging.info("[LOGIN] Successfully verified!")
        else:
            passwordField = self.utils.waitUntilClickable(By.NAME, "passwd")
            logging.info("[LOGIN] Entering password...")
            passwordField.click()
            passwordField.send_keys(self.browser.password)
            assert passwordField.get_attribute("value") == self.browser.password
            self.utils.waitUntilClickable(By.ID, "idSIButton9").click()

            isDeviceAuthEnabled = False
            with contextlib.suppress(TimeoutException):
                self.utils.waitUntilVisible(By.ID, "idSpan_SAOTCAS_DescSessionID")
                isDeviceAuthEnabled = True
            logging.debug("isDeviceAuthEnabled = %s", isDeviceAuthEnabled)

            isTOTPEnabled = False
            with contextlib.suppress(TimeoutException):
                self.utils.waitUntilVisible(By.ID, "idTxtBx_SAOTCC_OTC", 1)
                isTOTPEnabled = True
            logging.debug("isTOTPEnabled = %s", isTOTPEnabled)

            if isDeviceAuthEnabled:
                raise LoginError(
                    "Device authentication not supported. Please use TOTP or disable 2FA."
                )

            if isTOTPEnabled:
                if self.browser.totp is not None:
                    logging.info("[LOGIN] Entering OTP...")
                    otp = TOTP(self.browser.totp.replace(" ", "")).now()
                    otpField = self.utils.waitUntilClickable(
                        By.ID, "idTxtBx_SAOTCC_OTC"
                    )
                    otpField.send_keys(otp)
                    assert otpField.get_attribute("value") == otp
                    self.utils.waitUntilClickable(
                        By.ID, "idSubmit_SAOTCC_Continue"
                    ).click()
                else:
                    assert CONFIG.browser.visible, (
                        "[LOGIN] 2FA detected, provide token in accounts.json or handle manually."
                    )
                    print(
                        "[LOGIN] 2FA detected, handle prompts and press enter when on"
                        " keep me signed in page."
                    )
                    input()

        self.check_locked_user()
        self.check_banned_user()

        try:
            self.utils.waitUntilVisible(By.NAME, "kmsiForm", 20)
            self.utils.waitUntilClickable(By.ID, "acceptButton", 10).click()
            logging.info("[LOGIN] Clicked 'Stay signed in' confirmation.")
        except TimeoutException:
            logging.warning("[LOGIN] 'Stay signed in' prompt not detected — skipping.")

        isAskingToProtect = self.utils.checkIfTextPresentAfterDelay(
            "protect your account", 5
        )
        logging.debug("isAskingToProtect = %s", isAskingToProtect)

        if isAskingToProtect:
            assert (
                CONFIG.browser.visible
            ), "Account protection detected, run in visible mode to handle login"
            print(
                "Account protection detected, handle prompts and press enter when on rewards page"
            )
            input()

        self.utils.waitUntilVisible(
            By.CSS_SELECTOR, 'html[data-role-name="RewardsPortal"]'
        )