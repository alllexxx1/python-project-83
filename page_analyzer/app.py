from flask import (
    Flask,
    render_template,
    redirect,
    request,
    url_for,
    flash,
    get_flashed_messages
)
import psycopg2
from psycopg2.extras import NamedTupleCursor
import os
from dotenv import load_dotenv
from urllib.parse import urlparse
import validators
from datetime import date
import requests
from bs4 import BeautifulSoup


app = Flask(__name__)

load_dotenv()
app.secret_key = os.environ.get('SECRET_KEY')

DATABASE_URL = os.getenv('DATABASE_URL')


@app.route('/', methods=['GET'])
def new_url():
    url = ''
    return render_template(
        'main_page.html',
        url=url
    )


@app.route('/urls', methods=['POST'])
def post_url():
    input_url = request.form.get('url')

    if not input_url:
        flash('URL обязателен', 'error')
        messages = get_flashed_messages(with_categories=True)
        return render_template_with_error_flash(input_url, messages)

    if len(input_url) > 255:
        flash('URL превышает 255 символов', 'error')
        messages = get_flashed_messages(with_categories=True)
        return render_template_with_error_flash(input_url, messages)

    url = urlparse(input_url)
    normalized_url = f'{url.scheme}://{url.hostname}'
    validated_url = validators.url(normalized_url)
    if not validated_url:
        flash('Некорректный URL', 'error')
        messages = get_flashed_messages(with_categories=True)
        return render_template_with_error_flash(input_url, messages)

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('SELECT name, id FROM urls WHERE name=%s',
                    (normalized_url,))
        url_data = cur.fetchone()
    conn.close()

    if url_data:
        id_ = url_data.id
        flash('Страница уже существует', 'info')
        return redirect(
            url_for('get_url', id=id_), code=302
        )

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO urls (name, created_at)
            VALUES (%s, %s);
            """,
                    (normalized_url, date.today()))
    conn.commit()
    conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('SELECT id FROM urls WHERE name=%s', (normalized_url,))
        id_ = cur.fetchone().id
    conn.close()

    flash('Страница успешно добавлена', 'success')
    return redirect(
        url_for('get_url', id=id_), code=302
    )


@app.route('/urls', methods=['GET'])
def get_urls():
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('SELECT id, name FROM urls ORDER BY id DESC')
        urls_data = cur.fetchall()
    conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        latest_checks = {}
        cur.execute('''
            SELECT url_id, MAX(created_at) AS latest_created_at, status_code
            FROM url_checks
            GROUP BY url_id, status_code
            ORDER BY url_id DESC''')
        for row in cur.fetchall():
            latest_checks[row.url_id] = {
                'latest_created_at': row.latest_created_at,
                'status_code': row.status_code
            }
    conn.close()

    result_data = []
    for url in urls_data:
        latest_check_data = latest_checks.get(url.id, None)
        result_data.append({
            'id': url.id,
            'name': url.name,
            'check_created_at': latest_check_data['latest_created_at']
            if latest_check_data else None,
            'status_code': latest_check_data['status_code']
            if latest_check_data else None
        })
    return render_template(
        'index.html',
        urls=result_data
    )


@app.route('/urls/<id>', methods=['GET'])
def get_url(id):
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor() as cur:
        cur.execute('SELECT id FROM urls WHERE id=%s', (id,))
        id_ = cur.fetchone()
    conn.close()
    if not id_:
        return render_template('not_found.html'), 404

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('SELECT * FROM urls WHERE id=%s', (id,))
        url_data = cur.fetchone()
    conn.close()

    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('''
            SELECT *
            FROM url_checks WHERE url_id=%s
            ORDER BY id DESC''', (id,))
        checks = cur.fetchall()
    conn.close()

    messages = get_flashed_messages(with_categories=True)
    return render_template(
        'show.html',
        url=url_data,
        checks=checks,
        messages=messages
    )


@app.route('/urls/<id>/checks', methods=['POST'])
def check_url(id):
    conn = psycopg2.connect(DATABASE_URL)
    with conn.cursor(cursor_factory=NamedTupleCursor) as cur:
        cur.execute('SELECT name FROM urls WHERE id=%s', (id,))
        url = cur.fetchone().name
    conn.close()

    try:
        response = requests.get(url)
        status_code = response.status_code

        if status_code == 200:
            site_data = get_seo_info(response)

            conn = psycopg2.connect(DATABASE_URL)
            with conn.cursor() as cur:
                cur.execute("""
                       INSERT INTO url_checks (url_id, status_code, h1,
                       title, description, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s);
                       """,
                            (id, status_code,
                             site_data['h1'],
                             site_data['title'],
                             site_data['description'],
                             date.today()))
            conn.commit()
            conn.close()
            flash('Страница успешно проверена', 'success')

        else:
            flash('Произошла ошибка при проверке', 'error')

    except requests.RequestException:
        flash('Произошла ошибка при проверке', 'error')

    return redirect(
        url_for('get_url', id=id), code=302
    )


@app.errorhandler(404)
def not_found(error):
    return render_template('not_found.html'), 404


def render_template_with_error_flash(url, messages):
    return render_template(
        'main_page.html',
        url=url,
        messages=messages
    ), 422


def get_seo_info(web_page):
    soup = BeautifulSoup(web_page.text, 'html.parser')
    site_data = {}

    if soup.h1:
        site_data['h1'] = soup.h1.text
    else:
        site_data['h1'] = ''

    if soup.title:
        site_data['title'] = soup.title.text
    else:
        site_data['title'] = ''

    if soup.find('meta', attrs={'name': 'description'}):
        site_data['description'] = (
            soup.find('meta', attrs={'name': 'description'}).get('content'))
    else:
        site_data['description'] = ''

    return site_data
