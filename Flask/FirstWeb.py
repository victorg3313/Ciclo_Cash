from flask import Flask, render_template, request, redirect, url_for, session, flash
import pymysql
import os
from werkzeug.utils import secure_filename
import shutil

app = Flask('Control de Prestamos')
app.secret_key = ' ' 

# Configuración de la conexión a la base de datos
conexion = pymysql.connect(
    host='localhost',
    user='CicloCash',
    password='Choflas20311@',
    database='ciclocash'
)

# Configuración para subir archivos
UPLOAD_FOLDER = 'static/uploads'
ADDITIONAL_FOLDER = '/ruta/completa/a/tu/directorio'  # Cambia esto por la ruta completa a tu directorio
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(ADDITIONAL_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ADDITIONAL_FOLDER'] = ADDITIONAL_FOLDER

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    # Verificación de usuario en la base de datos
    with conexion.cursor() as cursor:
        cursor.execute("SELECT * FROM usuarios WHERE id = %s AND contraseña = %s", (username, password))
        user = cursor.fetchone()

    if user:
        session['username'] = username
        return redirect(url_for('dashboard'))
    flash('Credenciales inválidas', 'danger')
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    try:
        with conexion.cursor() as cursor:
            # Filtrar los clientes por el usuario que ha iniciado sesión
            cursor.execute("""
                SELECT id, nombre, apellido, direccion, telefono, prestamo 
                FROM clientes_oficial 
                WHERE prestamo > 0 AND usuario_id = %s
            """, (session['username'],))
            clientes_con_deuda = cursor.fetchall() or []

            # Convierte la salida de cursor.fetchall() en una lista de diccionarios
            clientes_con_deuda = [dict(id=row[0], nombre=row[1], apellido=row[2], direccion=row[3], telefono=row[4], prestamo=row[5]) for row in clientes_con_deuda]

            cursor.execute("SELECT COUNT(*) FROM clientes_oficial WHERE usuario_id = %s", (session['username'],))
            total_clientes = cursor.fetchone()[0] or 0
    except Exception as e:
        print("Error al consultar la base de datos:", e)
        clientes_con_deuda = []
        total_clientes = 0

    return render_template('dashboard.html', username=session['username'],
                           clientes_con_deuda=clientes_con_deuda,
                           total_clientes=total_clientes)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Validar que el nombre de usuario no esté ya registrado
        with conexion.cursor() as cursor:
            cursor.execute("SELECT * FROM usuarios WHERE id = %s", (username,))
            existing_user = cursor.fetchone()

            if existing_user:
                flash('El nombre de usuario ya está en uso', 'danger')
            else:
                # Insertar el nuevo usuario
                try:
                    cursor.execute("INSERT INTO usuarios (id, contraseña) VALUES (%s, %s)", (username, password))
                    conexion.commit()
                    flash('Usuario registrado con éxito', 'success')
                    return redirect(url_for('home'))
                except Exception as e:
                    flash(f'Ocurrió un error al registrar el usuario: {e}', 'danger')
                    
    return render_template('registro.html')

@app.route('/nuevo_cliente', methods=['GET', 'POST'])
def nuevo_cliente():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        nombre = request.form['nombre']
        apellido = request.form['apellido']
        telefono = request.form['telefono']
        direccion = request.form['direccion']
        aval = request.form['aval']
        telefono_aval = request.form['telefono_aval']
        prestamo = float(request.form['prestamo'])
        usuario_id = session['username']  # Usar el nombre de usuario de la sesión

        # Manejo de archivos
        credencial_cliente = request.files['credencial_cliente']
        credencial_aval = request.files['credencial_aval']
        comprobante_domicilio = request.files['comprobante_domicilio']

        # Validar tipos de archivos
        if not (credencial_cliente.content_type.startswith('image/') and
                credencial_aval.content_type.startswith('image/') and
                comprobante_domicilio.content_type.startswith('image/')):
            flash('Solo se permiten archivos de tipo imagen', 'danger')
            return redirect(url_for('nuevo_cliente'))

        try:
            # Guardar los archivos subidos
            credencial_cliente_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(credencial_cliente.filename))
            credencial_aval_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(credencial_aval.filename))
            comprobante_domicilio_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(comprobante_domicilio.filename))

            credencial_cliente.save(credencial_cliente_path)
            credencial_aval.save(credencial_aval_path)
            comprobante_domicilio.save(comprobante_domicilio_path)

            # Insertar nuevo cliente sin el préstamo calculado
            with conexion.cursor() as cursor:
                sql = """
                INSERT INTO clientes_oficial (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                               credencial_cliente, credencial_aval, comprobante_domicilio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                cursor.execute(sql, (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                     credencial_cliente_path, credencial_aval_path, comprobante_domicilio_path))
                conexion.commit()

            # Obtener el ID del cliente registrado para redirigir a métodos de pago
            cliente_id = cursor.lastrowid
            return redirect(url_for('metodos_pago', id_cliente=cliente_id, prestamo=prestamo))
        except Exception as e:
            print("Error al insertar datos:", e)
            return "Error al registrar el cliente", 500

    return render_template('nuevo_cliente.html')

@app.route('/metodos_pago/<int:id_cliente>/<float:prestamo>', methods=['GET', 'POST'])
def metodos_pago(id_cliente, prestamo):
    if 'username' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        meses = int(request.form['meses'])
        dia_pago = request.form['dia_pago']

        # Calcular el interés basado en los meses seleccionados
        if meses == 3:
            interes = 0.05
        elif meses == 6:
            interes = 0.10
        elif meses == 9:
            interes = 0.20
        elif meses == 12:
            interes = 0.25

        prestamo_con_interes = prestamo * (1 + interes)

        try:
            # Actualizar el préstamo del cliente con el interés calculado
            with conexion.cursor() as cursor:
                sql_update = "UPDATE clientes_oficial SET prestamo = %s, dia_pago = %s WHERE id = %s"
                cursor.execute(sql_update, (prestamo_con_interes, dia_pago, id_cliente))
                conexion.commit()

            flash('Método de pago registrado con éxito', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print("Error al actualizar datos:", e)
            return "Error al registrar el método de pago", 500

    return render_template('metodos_pago.html', id_cliente=id_cliente, prestamo=prestamo)

@app.route('/registro_pago', methods=['POST'])
def registro_pago():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    id_cliente = request.form['id_cliente']
    monto_pagado = float(request.form['monto_pagado'])

    try:
        with conexion.cursor() as cursor:
            # Obtener el prestamo actual del cliente
            cursor.execute("SELECT prestamo FROM clientes_oficial WHERE id = %s", (id_cliente,))
            prestamo_actual = cursor.fetchone()[0]

            # Validar que el monto a abonar no sea mayor que la deuda y sea mayor o igual a 1
            if monto_pagado > prestamo_actual:
                flash('El monto a abonar no puede ser mayor a la deuda. Pago mayor a la deuda.', 'danger')
                return redirect(url_for('dashboard'))
            if monto_pagado < 1:
                flash('El monto a abonar debe ser mayor o igual a 1. Este pago no se puede realizar.', 'danger')
                return redirect(url_for('dashboard'))

            # Insertar el nuevo pago en la tabla 'pagos'
            sql = "INSERT INTO pagos (id_cliente, monto_pagado) VALUES (%s, %s)"
            cursor.execute(sql, (id_cliente, monto_pagado))
            
            # Actualizar la deuda del cliente en la tabla 'clientes_oficial'
            sql_update = "UPDATE clientes_oficial SET prestamo = prestamo - %s WHERE id = %s"
            cursor.execute(sql_update, (monto_pagado, id_cliente))
            conexion.commit()
            
        flash('Pago registrado con éxito', 'success')
    except Exception as e:
        print("Error al registrar el pago:", e)
        flash('Error al registrar el pago', 'danger')
    
    return redirect(url_for('dashboard'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

if __name__ == '__main__':
    app.run(debug = True, host='0.0.0.0', port=5000)
