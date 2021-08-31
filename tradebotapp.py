import configparser
import os
import threading
import time

import requests
from flask import Flask, request
from binance.client import Client
from binance.exceptions import BinanceAPIException
from dotenv import load_dotenv

app = Flask(__name__)

env_path = os.path.dirname(os.path.realpath(__file__)) + '/.env'
load_dotenv(dotenv_path=env_path)

config = configparser.ConfigParser(interpolation=None)
config.read('config.ini')

client = Client(config['Settings']['API_KEY'], config['Settings']['API_SECRET'])

process = threading.Thread()


def get_dotenv(env):
    try:
        load_dotenv(override=True)
        val = os.getenv(env)
        return val
    except:
        return None


def set_dotenv(key, value):  # string
    global env_path
    if key:
        if not value:
            value = '\'\''
        cmd = 'dotenv -f ' + env_path + ' set ' + key + ' ' + value  # set env variable
        os.system(cmd)


@app.route('/notify', methods=['POST'])
def notify_getter():
    if int(get_dotenv('on_pause')):
        return ''

    content = request.get_json()
    data = content['text'].split(' ')

    if len(data) != 6:
        return 'error'

    asset = data[0] + data[1]
    currency = data[1]
    cryptocurrency = data[0]
    action = data[2]
    amount_percent = float(data[3].strip('%')) / 100
    stop_percent = float(data[4].strip('%')) / 100
    sleep_time_sec = float(data[5]) * 60

    global process
    if action.upper() == 'BUY' and int(get_dotenv('is_next_step_buy')):
        price_asset_after_buy = -1
        try:
            price_asset = get_price(asset)
            quantity = to_fixed(float(get_balance(currency)['free']) * amount_percent / price_asset, 5)
            price_asset_after_buy = order_market_buy(quantity, asset)
            set_dotenv('is_next_step_buy', '0')
        except BinanceAPIException as ex:
            if ex.message == 'Filter failure: LOT_SIZE':
                decimal_place = 15
                while decimal_place > -1:
                    try:
                        price_asset = get_price(asset)
                        quantity = to_fixed(float(get_balance(currency)['free']) * amount_percent / price_asset, decimal_place)
                        price_asset_after_buy = order_market_buy(quantity, asset)
                        set_dotenv('is_next_step_buy', '0')
                        break
                    except:
                        decimal_place -= 1

            if ex.code == -1013:
                send_notify_telegram('Стоимость ордера ниже минимальной! Покупка невозможна!')
                return ''
            send_notify_telegram(f'[{ex.code}]' + ex.message)
            return ''

        send_notify_telegram(success_buy_message(asset, currency, cryptocurrency))

        process = threading.Thread(target=check_asset_price,
                                   args=(price_asset_after_buy, stop_percent, sleep_time_sec,
                                         asset, currency, cryptocurrency,))
        set_dotenv('finish_check', '0')
        process.start()
    elif action.upper() == 'SELL' and not int(get_dotenv('is_next_step_buy')):
        try:
            order_market_sell(to_fixed(float(get_balance(cryptocurrency)['free']), 5), asset)
            set_dotenv('is_next_step_buy', '1')
        except BinanceAPIException as ex:
            if ex.message == 'Filter failure: LOT_SIZE':
                decimal_place = 15
                while decimal_place > -1:
                    try:
                        order_market_sell(to_fixed(float(get_balance(cryptocurrency)['free']), decimal_place), asset)
                        set_dotenv('is_next_step_buy', '1')
                        break
                    except:
                        decimal_place -= 1
            send_notify_telegram(f'[{ex.code}]' + ex.message)
            return ''

        send_notify_telegram(success_sell_message(asset, currency, cryptocurrency))
        set_dotenv('finish_check', '1')
        process.join()

    return ''


def check_asset_price(buy_price, stop_percent, sleep_time_sec, asset, currency, cryptocurrency):
    while True:
        if int(get_dotenv('finish_check')):
            break

        max_price_failing = buy_price - (buy_price * stop_percent)
        cur_price_asset = get_price(asset)

        if cur_price_asset <= max_price_failing:
            set_dotenv('on_pause', '1')
            try:
                order_market_sell(to_fixed(float(get_balance(cryptocurrency)['free']), 5), asset)
                set_dotenv('is_next_step_buy', '1')
            except BinanceAPIException as ex:
                send_notify_telegram(f'[{ex.code}]' + ex.message)
                set_dotenv('on_pause', '0')
                continue

            send_notify_telegram(success_sell_message(asset, currency, cryptocurrency, is_fail=1))

            time.sleep(sleep_time_sec)
            set_dotenv('on_pause', '0')
            return

        time.sleep(2)


def success_buy_message(asset, currency, cryptocurrency):
    data = get_history(asset)[-1]
    return f"""<b>Покупка</b>
    <code>
    Актив: {data['symbol']}
    Покупка: {data['commissionAsset']}
    Купленный актив: {data['qty']} {data['commissionAsset']}
    Проданный актив: {data['quoteQty']} {currency}
    Цена на момент покупки: {data['price']} {currency}
    Комиссия: {data['commission']} {cryptocurrency}
    Время сделки: {data['time']}</code>
    """


def success_sell_message(asset, currency, cryptocurrency, is_fail=0):
    data = get_history(asset)[-1]
    type_sell = 'Продажа' if not is_fail else 'Стоп-продажа'
    return f"""<b>{type_sell}</b>
    <code>
    Актив: {data['symbol']}
    Покупка: {data['commissionAsset']}
    Купленный актив: {data['quoteQty']} {data['commissionAsset']}
    Проданный актив: {data['qty']} {cryptocurrency}
    Цена на момент продажи: {data['price']} {cryptocurrency}
    Комиссия: {data['commission']} {currency}
    Время сделки: {data['time']}
    </code>
    
    <b>Информация о балансе:</b>
    <code>
    Баланс {currency}: {get_balance(currency)['free']}
    Баланс {cryptocurrency}: {get_balance(cryptocurrency)['free']}
    </code>
    """


def send_notify_telegram(msg):
    requests.get(f'https://api.telegram.org/bot{config["Settings"]["TOKEN_BOT"]}/sendMessage?'
                 f'chat_id={config["Settings"]["USER_ID"]}&text={msg}&parse_mode=HTML')


def get_balance(symbol):
    balance = client.get_asset_balance(asset=symbol)
    balance = {'free': balance['free'], 'locked': balance['locked']}
    return balance


def get_history(symbol):
    history = client.get_my_trades(symbol=symbol)
    return history


def get_price(symbol):
    price = client.get_symbol_ticker(symbol=symbol)['price']
    return float(price)


def order_market_buy(quantity, asset):
    res = client.order_market_buy(symbol=asset, quantity=quantity)
    return float(res['fills'][0]['price'])


def order_market_sell(quantity, asset):
    client.order_market_sell(symbol=asset, quantity=quantity)


def to_fixed(f: float, n=0):
    a, b = str(f).split('.')
    return '{}.{}{}'.format(a, b[:n], '0' * (n - len(b)))


if __name__ == '__main__':
    app.run(host='0.0.0.0')
