from tradebotmain import app, set_dotenv

set_dotenv('is_next_step_buy', '1')
set_dotenv('on_pause', '0')
set_dotenv('finish_check', '0')

if __name__ == '__main__':
    app.run()
