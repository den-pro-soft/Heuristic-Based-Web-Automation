from shop_crawler import *
from selenium_helper import *
import nlp

from common_heuristics import *

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import Select

import sys
import re
import traceback
       

def find_links(driver, contains=None, not_contains=None, by_path=False):
    links = driver.find_elements_by_css_selector("a[href]")
    result = []
    for link in links:
        if not can_click(link):
            continue

        href = link.get_attribute("href")
        if driver.current_url == href:
            continue

        if by_path:
            text = link.get_attribute("href")
        else:
            text = link.get_attribute("outerHTML")

        if nlp.check_text(text, contains, not_contains):
            result.append(link)

    return result


def find_buttons_or_links(driver,
                          contains=None,
                          not_contains=None
                         ):
    links = driver.find_elements_by_css_selector("a[href]")
    buttons = driver.find_elements_by_tag_name("button")
    inputs = driver.find_elements_by_css_selector('input[type="button"]')
    submits = driver.find_elements_by_css_selector('input[type="submit"]')

    # Yield isn't good because context can change
    result = []
    for elem in links + buttons + inputs + submits:
        if not can_click(elem):
            continue

        text = elem.get_attribute("outerHTML")
        if nlp.check_text(text, contains, not_contains):
            result.append(elem)

    return result

def to_string(element):
    try:
        return element.get_attribute("outerHTML")
    except:
        return str(element)


def click_first(driver, elements, on_error=None):
    def process(element):
        try:
            # process links by opening url
            href = element.get_attribute("href")
            if href and driver.current_url != href:
                driver.get(href)
                return True

            ActionChains(driver).move_to_element(element).perform()

            old_windows = len(driver.window_handles)
            element.click()
            new_windows = len(driver.window_handles)

            if new_windows > old_windows:
                driver.switch_to_window(driver.window_handles[-1])

            return True
        
        except WebDriverException:
            logger = logging.getLogger('shop_crawler')
            logger.debug('Unexpected exception during clicking element {}'.format(traceback.format_exc()))
            return False

    logger = logging.getLogger('shop_crawler')
            
    for element in elements:
        logger.debug('clicking element: {}'.format(to_string(element)))
        clicked = process(element)
        logger.debug('result: {}'.format(clicked))
                     
        if clicked:
            return True

        if on_error and on_error(driver):
            if process(element):
                return True

    return False


def try_handle_popups(driver):
    btns = find_buttons_or_links(driver, ["i .*over", "i .*age", ".* agree .*"], [' .*not.*', " .*under.*"])
    return click_first(driver, btns)


class ToProductPageLink(IStepActor):
    def get_states(self):
        return [States.new, States.shop]

    def find_to_product_links(self, driver):
        return find_links(driver, ['/product', '/commodity', '/drug'], by_path=True)

    def process_page(self, driver, state, context):
        links = self.find_to_product_links(driver)
        if click_first(driver, links):
            return States.product_page
        else:
            return state


class AddToCart(IStepActor):
    def get_states(self):
        return [States.new, States.shop, States.product_page]

    def filter_button(self, button):
        text = button.get_attribute('innerHTML')
        words = nlp.tokenize(text)
        if 'buy' in words:
            return len(words) <= 2
        
        return True
        
    def find_to_cart_elements(self, driver):
        btns = find_buttons_or_links(driver, ["add to cart",
                                              "add to bag",
                                              "buy"], ['where'])
        return list([btn for btn in btns if self.filter_button(btn)])

    def process_page(self, driver, state, context):
        elements = self.find_to_cart_elements(driver)
        if click_first(driver, elements, try_handle_popups):
            return States.product_in_cart
        else:
            return state


class ToShopLink(IStepActor):
    def get_states(self):
        return [States.new]

    def find_to_shop_elements(self, driver):
        return find_buttons_or_links(driver, ["shop", "store", "products"], ["shops", "stores"])

    def process_page(self, driver, state, context):
        elements = self.find_to_shop_elements(driver)
        if click_first(driver, elements, try_handle_popups):
            return States.shop
        else:
            return state


class ToCartLink(IStepActor):
    def find_to_cart_links(self, driver):
        return find_links(driver, ["cart"], ['add', 'append'], by_path=True)

    def get_states(self):
        return [States.product_in_cart]

    def process_page(self, driver, state, context):
        btns = self.find_to_cart_links(driver)

        if click_first(driver, btns):
            time.sleep(30)
            if not is_empty_cart(driver):
                return States.cart_page
        
        return state


class ToCheckout(IStepActor):

    def find_checkout_elements(self, driver):
        return find_buttons_or_links(driver, ["checkout", "check out"])

    def get_states(self):
        return [States.product_in_cart, States.cart_page]

    def process_page(self, driver, state, context):
        btns = self.find_checkout_elements(driver)

        if click_first(driver, btns):
            time.sleep(30)
            if not is_empty_cart(driver):
                return States.checkout_page
        
        return state

    
class GoogleForProductPage(IStepActor):
    def get_states(self):
        return [States.new, States.shop, States.product_page]
        
    def search(self, driver, google_query):
        driver.get('http://google.com')
        search_input = driver.find_element_by_css_selector('input.gsfi')
        search_input.clear()
        search_input.send_keys(google_query)
        search_input.send_keys(Keys.ENTER)
        
        # Check if no exact results
        statuses = driver.find_elements_by_css_selector('div.obp div.med')
        for status in statuses:
            if re.search(google_query, status.text):
                return None
        
        links = driver.find_elements_by_css_selector('div.g .rc .r a[href]')
        if len(links) > 0:
            return links[0].get_attribute("href")
        else:
            return None
    
    def search_for_product_link(self, driver, domain):
        queries = ['"add to cart"']

        # Open a new tab
        new_tab(driver)
        driver.get('https://google.com')
        for query in queries:
            google_query = 'site:{} {}'.format(domain, query)
            link = self.search(driver, google_query)
            if link:
                break
        
        # Close new tab
        close_tab(driver)
        
        return link
    
    def process_page(self, driver, state, context):
        link = self.search_for_product_link(driver, context.domain)
        
        if link:
            url = ShopCrawler.normalize_url(link)
            driver.get(url)
            return States.product_page
        
        return state
    
       
def add_crawler_extensions(crawler):
    crawler.add_handler(AddToCart(), 4)
    crawler.add_handler(GoogleForProductPage(), 3)
    crawler.add_handler(ToProductPageLink(), 2)
    crawler.add_handler(ToShopLink(), 1)
    crawler.add_handler(ToCheckout(), 3)
    crawler.add_handler(ToCartLink(), 2)
    