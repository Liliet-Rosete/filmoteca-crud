import os
from pathlib import Path
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import make_server
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import (create_engine, MetaData, Table, Column, Integer, String, Text,
                        select, insert, update, delete)

BASE = Path(__file__).resolve().parent
url = os.getenv('DATABASE_URL')
if os.getenv('RENDER') and not url:
    raise RuntimeError('DATABASE_URL no configurada')
if url:
    url = url.replace('postgres://', 'postgresql+psycopg://', 1) if url.startswith('postgres://') else url.replace('postgresql://', 'postgresql+psycopg://', 1)
else:
    url = 'sqlite:///' + str(BASE / 'peliculas.db')
engine = create_engine(url, pool_pre_ping=True)
metadata = MetaData()
movies = Table('peliculas', metadata, Column('id', Integer, primary_key=True),
               Column('titulo', String(160), nullable=False), Column('anio', Integer, nullable=False),
               Column('director', String(120), nullable=False), Column('genero', String(100), nullable=False),
               Column('sinopsis', Text, nullable=False))
initial = Table('configuracion', metadata, Column('id', Integer, primary_key=True))
with engine.begin() as conn:
    metadata.create_all(conn)
    if conn.execute(select(initial.c.id)).first() is None:
        conn.execute(insert(movies), [
            dict(titulo='Interestelar', anio=2014, director='Christopher Nolan', genero='Ciencia ficción', sinopsis='Un grupo de exploradores viaja más allá de nuestro sistema solar en busca de un nuevo hogar.'),
            dict(titulo='Coco', anio=2017, director='Lee Unkrich', genero='Animación', sinopsis='Miguel descubre la historia de su familia durante una aventura en el mundo de los muertos.'),
            dict(titulo='El gran hotel Budapest', anio=2014, director='Wes Anderson', genero='Comedia', sinopsis='Un conserje y su aprendiz se ven envueltos en una aventura alrededor de una herencia.')])
        conn.execute(insert(initial).values(id=1))

env = Environment(loader=FileSystemLoader(BASE / 'templates'), autoescape=select_autoescape(['html']))

def page(start, view, status='200 OK', **data):
    html = env.get_template('index.html').render(view=view, **data).encode('utf-8')
    start(status, [('Content-Type', 'text/html; charset=utf-8'), ('Content-Length', str(len(html)))])
    return [html]

def redirect(start, message):
    start('303 See Other', [('Location', '/?' + urlencode({'mensaje': message})), ('Content-Length', '0')])
    return [b'']

def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    if path == '/' and method == 'GET':
        with engine.connect() as conn:
            rows = conn.execute(select(movies).order_by(movies.c.id)).mappings().all()
        msg = parse_qs(environ.get('QUERY_STRING', '')).get('mensaje', [''])[0]
        return page(start_response, 'list', rows=rows, message=msg)
    parts = path.strip('/').split('/')
    if parts == ['nueva']:
        action, movie_id = 'nueva', None
    elif len(parts) == 2 and parts[0] in ('ver', 'editar', 'eliminar') and parts[1].isdigit() and len(parts[1]) < 10:
        action, movie_id = parts[0], int(parts[1])
    else:
        return page(start_response, 'error', status='404 Not Found')
    row = {}
    if movie_id is not None:
        with engine.connect() as conn:
            row = conn.execute(select(movies).where(movies.c.id == movie_id)).mappings().first()
        if row is None:
            return page(start_response, 'error', status='404 Not Found')
    if action == 'ver' and method == 'GET':
        return page(start_response, 'detail', row=row)
    if action == 'eliminar' and method == 'POST':
        with engine.begin() as conn:
            conn.execute(delete(movies).where(movies.c.id == movie_id))
        return redirect(start_response, 'Película eliminada correctamente.')
    if action in ('nueva', 'editar'):
        if method == 'GET':
            return page(start_response, 'form', row=row, action=action)
        if method == 'POST':
            length = int(environ.get('CONTENT_LENGTH') or 0)
            if length > 20000:
                return page(start_response, 'error', status='413 Payload Too Large')
            form = parse_qs(environ['wsgi.input'].read(length).decode('utf-8'), keep_blank_values=True)
            data = {k: form.get(k, [''])[0].strip() for k in ('titulo','anio','director','genero','sinopsis')}
            try:
                year = int(data['anio'])
                assert 1888 <= year <= 2100
                assert all(data.values()) and all(len(data[k]) <= n for k,n in [('titulo',160),('director',120),('genero',100),('sinopsis',3000)])
            except (ValueError, AssertionError):
                return page(start_response, 'form', status='400 Bad Request', row=data, action=action, error='Completa todos los campos e introduce un año válido (1888–2100).')
            data['anio'] = year
            with engine.begin() as conn:
                if action == 'nueva':
                    conn.execute(insert(movies).values(**data))
                else:
                    conn.execute(update(movies).where(movies.c.id == movie_id).values(**data))
            return redirect(start_response, 'Película agregada correctamente.' if action == 'nueva' else 'Película actualizada correctamente.')
    return page(start_response, 'error', status='405 Method Not Allowed')

if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    print(f'http://localhost:{port}', flush=True)
    make_server('0.0.0.0', port, application).serve_forever()
