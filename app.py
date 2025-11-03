from flask import Flask, render_template, request, redirect, url_for, session, flash
# Importamos el conector de PostgreSQL. Necesitarás instalarlo: pip install psycopg2-binary
import psycopg2 
import psycopg2.extras # Para manejar fetchall como diccionarios
import os
from werkzeug.utils import secure_filename
import shutil

# --- CONFIGURACIÓN DE LA APLICACIÓN ---
app = Flask('Control de Prestamos')
app.secret_key = os.environ.get('SECRET_KEY', 'default_secret_key_change_me') # Usar variable de entorno para la clave secreta

# --- CONFIGURACIÓN DE LA BASE DE DATOS (POSTGRESQL/SUPABASE) ---
# OBLIGATORIO: Leer la URL de conexión completa de Supabase desde las variables de entorno de Render
DATABASE_URL = os.environ.get('DATABASE_URL') 
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL no está configurada. Necesita la URL de conexión de Supabase.")

def get_db_connection():
    """Función para establecer y devolver una nueva conexión a la base de datos."""
    try:
        # Usamos la URL completa proporcionada por Supabase (ej: postgresql://user:pass@host:port/dbname)
        conn = psycopg2.connect(DATABASE_URL) 
        return conn
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")
        # En producción, es mejor lanzar una excepción o manejar el fallo de conexión
        raise

# --- CONFIGURACIÓN PARA SUBIR ARCHIVOS ---
# NOTA: En Render, los archivos subidos al disco efímero se pierden al reiniciar.
# Para persistencia de archivos, DEBES usar un servicio de almacenamiento en la nube (ej. AWS S3, Supabase Storage).
# Por ahora, mantenemos la lógica local, pero ten en cuenta la limitación.
UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Eliminamos ADDITIONAL_FOLDER ya que es una ruta local y no funcionará en Render
os.makedirs(UPLOAD_FOLDER, exist_ok=True) 

# --- RUTAS DE LA APLICACIÓN ---

@app.route('/')
def home():
    return render_template('login.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    conn = None
    try:
        conn = get_db_connection()
        # El cursor de DictCursor permite obtener los resultados como diccionarios, más fácil de manejar.
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # PostgreSQL usa %s como marcador de posición.
            cursor.execute("""
                SELECT id, contraseña FROM usuarios WHERE id = %s AND contraseña = %s
            """, (username, password))
            user = cursor.fetchone()

        if user:
            session['username'] = username
            return redirect(url_for('dashboard'))
        flash('Credenciales inválidas', 'danger')
        return redirect(url_for('home'))
    except Exception as e:
        print(f"Error en el login: {e}")
        flash('Error interno del servidor', 'danger')
        return redirect(url_for('home'))
    finally:
        if conn:
            conn.close()

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    conn = None
    clientes_con_deuda = []
    total_clientes = 0

    try:
        conn = get_db_connection()
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cursor:
            # Consulta para clientes con deuda
            cursor.execute("""
                SELECT id, nombre, apellido, direccion, telefono, prestamo
                FROM clientes_oficial
                WHERE prestamo > 0 AND usuario_id = %s
            """, (session['username'],))
            # fetchall() devuelve una lista de diccionarios gracias a DictCursor
            clientes_con_deuda = cursor.fetchall()

            # Consulta para el total de clientes
            cursor.execute("SELECT COUNT(*) FROM clientes_oficial WHERE usuario_id = %s", (session['username'],))
            total_clientes = cursor.fetchone()[0] or 0
    except Exception as e:
        print("Error al consultar la base de datos:", e)
        flash('Error al cargar el Dashboard.', 'danger')
    finally:
        if conn:
            conn.close()

    return render_template('dashboard.html', username=session['username'],
                           clientes_con_deuda=clientes_con_deuda,
                           total_clientes=total_clientes)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Validar que el nombre de usuario no esté ya registrado
                cursor.execute("SELECT id FROM usuarios WHERE id = %s", (username,))
                existing_user = cursor.fetchone()

                if existing_user:
                    flash('El nombre de usuario ya está en uso', 'danger')
                else:
                    # Insertar el nuevo usuario
                    cursor.execute("INSERT INTO usuarios (id, contraseña) VALUES (%s, %s)", (username, password))
                    conn.commit()
                    flash('Usuario registrado con éxito', 'success')
                    return redirect(url_for('home'))
        except Exception as e:
            print(f'Ocurrió un error al registrar el usuario: {e}')
            flash(f'Ocurrió un error al registrar el usuario: {e}', 'danger')
        finally:
            if conn:
                conn.close()
                
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
        try:
            prestamo = float(request.form['prestamo'])
        except ValueError:
            flash('El monto del préstamo no es válido.', 'danger')
            return redirect(url_for('nuevo_cliente'))
        
        usuario_id = session['username']
        
        # Manejo de archivos (simplificado)
        credencial_cliente = request.files.get('credencial_cliente')
        credencial_aval = request.files.get('credencial_aval')
        comprobante_domicilio = request.files.get('comprobante_domicilio')

        # Se asume que todos los archivos se adjuntaron, si no, se manejaría un error de clave.
        if not all([credencial_cliente, credencial_aval, comprobante_domicilio]):
             flash('Faltan archivos por subir.', 'danger')
             return redirect(url_for('nuevo_cliente'))

        # Lógica de guardado y ruta (Temporal para Render)
        try:
            credencial_cliente_filename = secure_filename(credencial_cliente.filename)
            credencial_aval_filename = secure_filename(credencial_aval.filename)
            comprobante_domicilio_filename = secure_filename(comprobante_domicilio.filename)
            
            credencial_cliente_path = os.path.join(app.config['UPLOAD_FOLDER'], credencial_cliente_filename)
            credencial_aval_path = os.path.join(app.config['UPLOAD_FOLDER'], credencial_aval_filename)
            comprobante_domicilio_path = os.path.join(app.config['UPLOAD_FOLDER'], comprobante_domicilio_filename)

            # Guardar archivos localmente (recuerda la limitación de persistencia de Render)
            credencial_cliente.save(credencial_cliente_path)
            credencial_aval.save(credencial_aval_path)
            comprobante_domicilio.save(comprobante_domicilio_path)

        except Exception as e:
            flash(f'Error al guardar archivos: {e}', 'danger')
            return redirect(url_for('nuevo_cliente'))

        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                sql = """
                INSERT INTO clientes_oficial (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                                credencial_cliente, credencial_aval, comprobante_domicilio)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id; -- PostgreSQL necesita RETURNING para obtener el ID
                """
                cursor.execute(sql, (nombre, apellido, telefono, direccion, aval, telefono_aval, prestamo, usuario_id,
                                     credencial_cliente_path, credencial_aval_path, comprobante_domicilio_path))
                
                # Obtener el ID del cliente registrado con RETURNING id
                cliente_id = cursor.fetchone()[0]
                conn.commit()

            return redirect(url_for('metodos_pago', id_cliente=cliente_id, prestamo=prestamo))
        except Exception as e:
            print("Error al insertar datos:", e)
            flash(f'Error al registrar el cliente: {e}', 'danger')
            return redirect(url_for('nuevo_cliente'))
        finally:
            if conn:
                conn.close()

    return render_template('nuevo_cliente.html')

@app.route('/metodos_pago/<int:id_cliente>/<float:prestamo>', methods=['GET', 'POST'])
def metodos_pago(id_cliente, prestamo):
    if 'username' not in session:
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        try:
            meses = int(request.form['meses'])
            dia_pago = int(request.form['dia_pago']) # Aseguramos que sea entero
        except ValueError:
            flash('Selecciones inválidas para meses o día de pago.', 'danger')
            return redirect(url_for('metodos_pago', id_cliente=id_cliente, prestamo=prestamo))

        # Calcular el interés basado en los meses seleccionados
        interes = 0.0
        if meses == 3:
            interes = 0.05
        elif meses == 6:
            interes = 0.10
        elif meses == 9:
            interes = 0.20
        elif meses == 12:
            interes = 0.25
        else:
            flash('Plazo de meses inválido.', 'danger')
            return redirect(url_for('metodos_pago', id_cliente=id_cliente, prestamo=prestamo))

        prestamo_con_interes = prestamo * (1 + interes)
        
        conn = None
        try:
            conn = get_db_connection()
            with conn.cursor() as cursor:
                # Actualizar el préstamo del cliente con el interés calculado
                sql_update = "UPDATE clientes_oficial SET prestamo = %s, dia_pago = %s WHERE id = %s"
                cursor.execute(sql_update, (prestamo_con_interes, dia_pago, id_cliente))
                conn.commit()

            flash('Método de pago registrado con éxito', 'success')
            return redirect(url_for('dashboard'))
        except Exception as e:
            print("Error al actualizar datos:", e)
            flash('Error al registrar el método de pago.', 'danger')
            return redirect(url_for('dashboard'))
        finally:
            if conn:
                conn.close()

    return render_template('metodos_pago.html', id_cliente=id_cliente, prestamo=prestamo)

@app.route('/registro_pago', methods=['POST'])
def registro_pago():
    if 'username' not in session:
        return redirect(url_for('home'))
    
    conn = None
    try:
        id_cliente = request.form['id_cliente']
        monto_pagado = float(request.form['monto_pagado'])
    except ValueError:
        flash('El monto pagado no es un valor numérico válido.', 'danger')
        return redirect(url_for('dashboard'))

    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # Obtener el prestamo actual del cliente
            cursor.execute("SELECT prestamo FROM clientes_oficial WHERE id = %s", (id_cliente,))
            result = cursor.fetchone()
            if not result:
                 flash('Cliente no encontrado.', 'danger')
                 return redirect(url_for('dashboard'))
                 
            prestamo_actual = result[0]

            # Validar que el monto a abonar no sea mayor que la deuda y sea mayor o igual a 1
            if monto_pagado > prestamo_actual:
                flash('El monto a abonar no puede ser mayor a la deuda.', 'danger')
                return redirect(url_for('dashboard'))
            if monto_pagado < 1:
                flash('El monto a abonar debe ser mayor o igual a 1.', 'danger')
                return redirect(url_for('dashboard'))

            # Insertar el nuevo pago en la tabla 'pagos'
            sql_insert_pago = "INSERT INTO pagos (id_cliente, monto_pagado) VALUES (%s, %s)"
            cursor.execute(sql_insert_pago, (id_cliente, monto_pagado))
            
            # Actualizar la deuda del cliente en la tabla 'clientes_oficial'
            sql_update_prestamo = "UPDATE clientes_oficial SET prestamo = prestamo - %s WHERE id = %s"
            cursor.execute(sql_update_prestamo, (monto_pagado, id_cliente))
            conn.commit()
            
        flash('Pago registrado con éxito', 'success')
    except Exception as e:
        print("Error al registrar el pago:", e)
        flash(f'Error al registrar el pago: {e}', 'danger')
    finally:
        if conn:
            conn.close()
            
    return redirect(url_for('dashboard'))

@app.route('/logout', methods=['POST'])
def logout():
    session.pop('username', None)
    return redirect(url_for('home'))

# --- PUNTO DE ENTRADA (Para Render) ---
if __name__ == '__main__':
    # Usamos Gunicorn en producción, pero esta es la configuración para desarrollo local
    app.run(debug=True, host='0.0.0.0', port=5000)
