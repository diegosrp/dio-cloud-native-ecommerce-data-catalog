import streamlit as st
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import AzureError
from PIL import Image, ImageOps, UnidentifiedImageError
import os
import pyodbc
import uuid
import logging
import math
import re
import warnings
from urllib.parse import urlparse, unquote
import html
from io import BytesIO
from dotenv import load_dotenv

# Load environment variables from the .env file.
load_dotenv()

# Define Azure Blob Storage configuration constants.
AZURE_BLOB_ACCOUNT_NAME = os.getenv('BLOB_ACCOUNT_NAME')
AZURE_BLOB_CONTAINER_NAME = os.getenv('BLOB_CONTAINER_NAME')

# Define SQL Server configuration constants.
DB_SERVER = os.getenv('SQL_SERVER')
DB_NAME = os.getenv('SQL_DATABASE')
DB_AUTH_MODE = os.getenv('SQL_AUTH_MODE', 'entra-mi')
SQL_MANAGED_IDENTITY_CLIENT_ID = os.getenv('SQL_MANAGED_IDENTITY_CLIENT_ID')
AZURE_CLIENT_ID = os.getenv('AZURE_CLIENT_ID')
SQL_ODBC_DRIVER = os.getenv('SQL_ODBC_DRIVER', '{ODBC Driver 18 for SQL Server}')

MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024
ALLOWED_IMAGE_EXTENSIONS = ['jpg', 'jpeg', 'png']
ALLOWED_IMAGE_FORMATS = {'JPEG', 'PNG'}
ALLOWED_IMAGE_HELP_TEXT = 'JPEG (.jpg/.jpeg) and PNG (.png) up to 10 MB'
ALLOWED_IMAGE_ERROR_TEXT = 'Invalid image format. Please upload a JPEG or PNG image.'
MAX_DESCRIPTION_LENGTH = 1000
MAX_IMAGE_PIXELS = 16_000_000
MAX_IMAGE_DIMENSION = 8000
CATALOG_PAGE_SIZE_OPTIONS = [6, 9, 12]
CATALOG_DEFAULT_PAGE_SIZE = 9
PRODUCT_CACHE_TTL_SECONDS = 30
IMAGE_CACHE_TTL_SECONDS = 300

logger = logging.getLogger('catalog_app')
if not logger.handlers:
    logging.basicConfig(level=os.getenv('LOG_LEVEL', 'INFO').upper())


def show_error_to_user(user_message, context, include_traceback=True):
    # Show a user-friendly error and log technical details with a correlation ID.
    error_id = uuid.uuid4().hex[:12]
    if include_traceback:
        logger.exception('error_id=%s context=%s', error_id, context)
    else:
        logger.error('error_id=%s context=%s', error_id, context)
    st.error(f'{user_message} (Error ID: {error_id})')


def validate_runtime_configuration():
    # Validate required runtime configuration and stop on unsupported values.
    required_env_vars = {
        'BLOB_ACCOUNT_NAME': AZURE_BLOB_ACCOUNT_NAME,
        'BLOB_CONTAINER_NAME': AZURE_BLOB_CONTAINER_NAME,
        'SQL_SERVER': DB_SERVER,
        'SQL_DATABASE': DB_NAME,
    }
    missing_env_vars = [name for name, value in required_env_vars.items() if not (value or '').strip()]
    if missing_env_vars:
        show_error_to_user(
            'Application configuration is incomplete. Contact support.',
            context=f"missing_env_vars={','.join(missing_env_vars)}",
            include_traceback=False,
        )
        st.stop()

    if DB_AUTH_MODE.lower() != 'entra-mi':
        show_error_to_user(
            'Database authentication mode is not supported for this app.',
            context=f'invalid_sql_auth_mode={DB_AUTH_MODE}',
            include_traceback=False,
        )
        st.stop()


def sanitize_blob_filename(filename):
    # Sanitize user-provided file names into safe and predictable blob names.
    base_name = os.path.basename(filename or '').strip()
    if not base_name:
        return 'image'

    sanitized = re.sub(r'[^A-Za-z0-9._-]+', '-', base_name).strip('._-')
    if not sanitized:
        return 'image'

    name_part, extension = os.path.splitext(sanitized)
    safe_name_part = (name_part[:80] or 'image').strip('._-') or 'image'
    safe_extension = extension.lower()[:10]
    return f'{safe_name_part}{safe_extension}'


validate_runtime_configuration()


# Render the main page title.
st.title('Manage Products')

st.markdown(
        """
        <style>
            .catalog-card {
                border: 1px solid var(--secondary-background-color);
                border-radius: 12px;
                padding: 12px;
                margin-bottom: 10px;
                background: var(--background-color);
            }
            .catalog-name {
                font-size: 1.05rem;
                font-weight: 700;
                color: var(--text-color);
                margin: 4px 0 8px 0;
            }
            .catalog-description {
                font-size: 0.92rem;
                color: var(--text-color);
                opacity: .9;
                margin: 0 0 4px 0;
            }
            .catalog-price {
                display: inline-block;
                margin-top: 10px;
                padding: 5px 11px;
                border-radius: 999px;
                border: 1px solid #C7D2FE;
                background: #EEF2FF;
                color: #1E3A8A;
                font-weight: 700;
                font-size: 0.82rem;
            }

            [data-theme="dark"] .catalog-price {
                border-color: #374151;
                background: #1F2937;
                color: #E5E7EB;
            }

            .catalog-image-wrap {
                width: 100%;
                aspect-ratio: 4 / 3;
                overflow: hidden;
                border-radius: 10px;
                margin-bottom: 10px;
            }

            .catalog-image {
                width: 100%;
                height: 100%;
                object-fit: cover;
                display: block;
            }

            /* Hide Streamlit image overlay controls when rendered. */
            [data-testid="stImage"] button {
                display: none !important;
            }
        </style>
        """,
        unsafe_allow_html=True,
)

if 'uploader_key' not in st.session_state:
    st.session_state.uploader_key = 0

if 'form_key' not in st.session_state:
    st.session_state.form_key = 0

if 'status_message' not in st.session_state:
    st.session_state.status_message = None

if 'status_type' not in st.session_state:
    st.session_state.status_type = 'success'

selected_tab = st.radio(
    'Navigation',
    ['Add product', 'Product catalog'],
    horizontal=True,
    label_visibility='collapsed'
)

if selected_tab == 'Product catalog' and st.session_state.status_message:
    st.session_state.status_message = None

if selected_tab == 'Add product' and st.session_state.status_message:
    if st.session_state.status_type == 'success':
        st.success(st.session_state.status_message)
    else:
        st.error(st.session_state.status_message)

if selected_tab == 'Add product':
    # Render product registration form fields.
    form_col, preview_col = st.columns([1.4, 1])

    with form_col:
        product_name = st.text_input('Product name', key=f"product_name_{st.session_state.form_key}")
        product_description = st.text_area(
            'Product description',
            key=f"product_description_{st.session_state.form_key}",
            max_chars=MAX_DESCRIPTION_LENGTH
        )
        product_price = st.number_input(
            'Product price',
            min_value=0.0,
            step=1.0,
            format='%.2f',
            key=f"product_price_{st.session_state.form_key}"
        )

    with preview_col:
        product_image = st.file_uploader(
            'Product image',
            type=ALLOWED_IMAGE_EXTENSIONS,
            help=ALLOWED_IMAGE_HELP_TEXT,
            key=f"product_image_{st.session_state.form_key}_{st.session_state.uploader_key}"
        )

    is_form_valid = (
        bool(product_name.strip())
        and bool(product_description.strip())
        and product_price > 0
        and product_image is not None
    )

    # Enable save only when all required fields are valid.
    save_product_clicked = st.button('Save product', disabled=(not is_form_valid))

def get_db_connection():
    # Create and return a SQL connection using managed identity authentication.
    available_drivers = pyodbc.drivers()
    preferred_drivers = [
        SQL_ODBC_DRIVER.strip('{}'),
        'ODBC Driver 18 for SQL Server',
        'ODBC Driver 17 for SQL Server',
    ]

    selected_driver = next((driver for driver in preferred_drivers if driver in available_drivers), None)
    if not selected_driver:
        raise ValueError(
            'No supported SQL ODBC driver found. Install ODBC Driver 18 or 17 for SQL Server on the App Service runtime.'
        )

    base_connection_string = (
        f"Driver={{{selected_driver}}};"
        f"Server=tcp:{DB_SERVER},1433;"
        f"Database={DB_NAME};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
        "Connection Timeout=30;"
    )

    connection_string = base_connection_string + "Authentication=ActiveDirectoryMsi;"
    if SQL_MANAGED_IDENTITY_CLIENT_ID:
        connection_string += f"UID={SQL_MANAGED_IDENTITY_CLIENT_ID};"
    return pyodbc.connect(connection_string, autocommit=False)


def ensure_products_table():
    # Create the Products table when it does not exist.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            IF OBJECT_ID('dbo.Products', 'U') IS NULL
            BEGIN
                CREATE TABLE dbo.Products (
                    Id INT IDENTITY(1,1) PRIMARY KEY,
                    Name NVARCHAR(255) NOT NULL,
                    Price DECIMAL(18,2) NOT NULL,
                    Description NVARCHAR(MAX) NULL,
                    ImageUrl NVARCHAR(2048) NULL,
                    CreatedAt DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
                )
            END
            """
        )
        conn.commit()
    except (pyodbc.Error, ValueError):
        show_error_to_user('Unable to initialize products storage right now.', context='ensure_products_table')
        st.stop()
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


# Ensure database schema exists during app startup.
ensure_products_table()


def get_blob_service_client():
    # Build a Blob service client using managed identity credentials.
    managed_identity_client_id = AZURE_CLIENT_ID or SQL_MANAGED_IDENTITY_CLIENT_ID
    credential = (
        DefaultAzureCredential(managed_identity_client_id=managed_identity_client_id)
        if managed_identity_client_id
        else DefaultAzureCredential()
    )

    account_url = f"https://{AZURE_BLOB_ACCOUNT_NAME}.blob.core.windows.net"
    return BlobServiceClient(
        account_url=account_url,
        credential=credential
    )


def upload_blob(uploaded_file):
    # Upload an image file to Blob Storage and return the blob URL.
    blob_service_client = get_blob_service_client()
    container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)
    safe_filename = sanitize_blob_filename(uploaded_file.name)
    blob_name = f"{uuid.uuid4()}-{safe_filename}"
    blob_client = container_client.get_blob_client(blob_name)
    uploaded_file.seek(0)
    blob_client.upload_blob(uploaded_file.read(), overwrite=True)
    image_url = blob_client.url
    return image_url


def delete_blob_image(image_url):
    # Delete an uploaded blob when the database write fails.
    blob_name = extract_blob_name(image_url)
    if not blob_name:
        return

    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)
        blob_client = container_client.get_blob_client(blob_name)
        blob_client.delete_blob(delete_snapshots='include')
    except AzureError:
        logger.exception('Unable to delete orphan blob for image_url=%s', image_url)


def extract_blob_name(image_url):
    # Extract the blob path from a stored image URL.
    sanitized_url = image_url.split('?', maxsplit=1)[0]
    marker = f"/{AZURE_BLOB_CONTAINER_NAME}/"
    if marker in sanitized_url:
        return unquote(sanitized_url.split(marker, maxsplit=1)[1])
    parsed_url = urlparse(sanitized_url)
    path_parts = [part for part in parsed_url.path.split('/') if part]
    if len(path_parts) >= 2:
        return unquote('/'.join(path_parts[1:]))
    return None


def download_blob_image(image_url):
    # Download image bytes through backend identity for private storage accounts.
    blob_name = extract_blob_name(image_url)
    if not blob_name:
        return None

    try:
        blob_service_client = get_blob_service_client()
        container_client = blob_service_client.get_container_client(AZURE_BLOB_CONTAINER_NAME)
        blob_client = container_client.get_blob_client(blob_name)
        return blob_client.download_blob().readall()
    except AzureError:
        logger.warning('Unable to download blob image for URL: %s', image_url)
        return None


def normalize_catalog_image(image_bytes, width=800, height=600):
    # Normalize images to a fixed 4:3 frame for consistent catalog cards.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(image_bytes)) as image_obj:
                source_width, source_height = image_obj.size
                if (
                    source_width <= 0
                    or source_height <= 0
                    or source_width > MAX_IMAGE_DIMENSION
                    or source_height > MAX_IMAGE_DIMENSION
                    or (source_width * source_height) > MAX_IMAGE_PIXELS
                ):
                    return None

                normalized = ImageOps.fit(image_obj.convert('RGB'), (width, height), Image.Resampling.LANCZOS)
                output = BytesIO()
                normalized.save(output, format='JPEG', quality=88, optimize=True)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None


def validate_uploaded_image(uploaded_file):
    # Validate uploaded image size, dimensions, and actual file format.
    if uploaded_file is None:
        return False, 'Product image is required.'

    if uploaded_file.size > MAX_IMAGE_SIZE_BYTES:
        return False, 'Image is too large. Maximum allowed size is 10 MB.'

    uploaded_file.seek(0)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(uploaded_file) as image_obj:
                detected_format = (image_obj.format or '').upper()
                image_width, image_height = image_obj.size
                if (
                    image_width <= 0
                    or image_height <= 0
                    or image_width > MAX_IMAGE_DIMENSION
                    or image_height > MAX_IMAGE_DIMENSION
                    or (image_width * image_height) > MAX_IMAGE_PIXELS
                ):
                    uploaded_file.seek(0)
                    return False, 'Image dimensions are too large for processing.'

                image_obj.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        uploaded_file.seek(0)
        return False, ALLOWED_IMAGE_ERROR_TEXT

    uploaded_file.seek(0)

    if detected_format not in ALLOWED_IMAGE_FORMATS:
        return False, ALLOWED_IMAGE_ERROR_TEXT

    return True, None


def insert_product(product_name_input, product_price_input, product_description_input, image_url_input):
    # Insert a new product row in SQL Server.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        # Use a parameterized query to prevent SQL injection.
        insert_sql = "INSERT INTO Products (Name, Price, Description, ImageUrl) VALUES (?, ?, ?, ?)"
        cursor.execute(insert_sql, (product_name_input, product_price_input, product_description_input, image_url_input))
        conn.commit()

        return True
    except (pyodbc.Error, ValueError):
        show_error_to_user('Unable to save product right now.', context='insert_product')
        return False
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()

@st.cache_data(ttl=PRODUCT_CACHE_TTL_SECONDS, show_spinner=False)
def get_cached_products():
    # Read products ordered by newest first using short-lived caching.
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT Id, Name, Price, Description, ImageUrl FROM Products ORDER BY Id DESC")
        columns = [column[0] for column in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]
        return rows
    finally:
        if cursor is not None:
            cursor.close()
        if conn is not None:
            conn.close()


def list_products():
    # Keep user-facing error handling outside cached execution.
    try:
        return get_cached_products()
    except (pyodbc.Error, ValueError):
        show_error_to_user('Unable to load products right now.', context='list_products')
        return []


@st.cache_data(ttl=IMAGE_CACHE_TTL_SECONDS, show_spinner=False)
def get_cached_catalog_image(image_url):
    # Cache normalized image bytes to reduce repeated blob downloads and processing.
    product_image_bytes = download_blob_image(image_url)
    if not product_image_bytes:
        return None
    return normalize_catalog_image(product_image_bytes)


def paginate_products(products):
    # Paginate products for faster rendering and lower blob read volume.
    if 'catalog_page_size' not in st.session_state:
        st.session_state.catalog_page_size = CATALOG_DEFAULT_PAGE_SIZE

    if 'catalog_page' not in st.session_state:
        st.session_state.catalog_page = 1

    controls_col1, controls_col2, controls_col3 = st.columns([1, 1, 2])
    with controls_col1:
        page_size = st.selectbox(
            'Items per page',
            options=CATALOG_PAGE_SIZE_OPTIONS,
            key='catalog_page_size',
        )

    total_products = len(products)
    total_pages = max(1, math.ceil(total_products / page_size))
    current_page = min(int(st.session_state.catalog_page), total_pages)

    with controls_col2:
        current_page = int(
            st.number_input(
                'Page',
                min_value=1,
                max_value=total_pages,
                value=current_page,
                step=1,
                format='%d',
            )
        )
    st.session_state.catalog_page = current_page

    start_index = (current_page - 1) * page_size
    end_index = min(start_index + page_size, total_products)
    with controls_col3:
        st.caption(f'Showing {start_index + 1}-{end_index} of {total_products} products')

    return products[start_index:end_index]


def list_products_screen():
    # Render products in a 3-column card grid with normalized image sizes.
    products = list_products()
    if products:
        paged_products = paginate_products(products)
        cards_per_row = 3
        cols = st.columns(cards_per_row)
        for i, product in enumerate(paged_products):
            col = cols[i % cards_per_row]
            with col:
                # Product fields mapped from SQL rows: Name, Description, Price, and ImageUrl.
                st.markdown("<div class='catalog-card'>", unsafe_allow_html=True)
                if product['ImageUrl']:
                    normalized_image_bytes = get_cached_catalog_image(product['ImageUrl'])
                    if normalized_image_bytes:
                        st.image(normalized_image_bytes, use_container_width=True)

                safe_name = html.escape(str(product.get('Name') or '-'))
                safe_description = html.escape(str(product.get('Description') or '-'))
                st.markdown(f"<div class='catalog-name'>{safe_name}</div>", unsafe_allow_html=True)
                st.markdown(
                    f"<p class='catalog-description'>{safe_description}</p>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='catalog-price'>NZD ${float(product.get('Price') or 0):.2f}</div>",
                    unsafe_allow_html=True,
                )
                st.markdown("</div>", unsafe_allow_html=True)
            # Start a new row of columns every N cards.
            if (i + 1) % cards_per_row == 0 and (i + 1) < len(paged_products):
                cols = st.columns(cards_per_row)
    else:
        st.info('No products found.')


if selected_tab == 'Add product' and save_product_clicked:
    is_valid_image, image_validation_error = validate_uploaded_image(product_image)
    if not is_valid_image:
        st.error(image_validation_error)
        st.stop()

    try:
        uploaded_image_url = upload_blob(product_image)
    except (AzureError, ValueError):
        show_error_to_user('Unable to upload image right now.', context='upload_blob')
        st.stop()

    is_product_saved = insert_product(
        product_name,
        product_price,
        product_description,
        uploaded_image_url
    )
    if is_product_saved:
        get_cached_products.clear()
        get_cached_catalog_image.clear()
        st.session_state.catalog_page = 1
        st.session_state.uploader_key += 1
        st.session_state.form_key += 1
        st.session_state.status_message = 'Product saved successfully!'
        st.session_state.status_type = 'success'
        st.rerun()
    else:
        delete_blob_image(uploaded_image_url)

if selected_tab == 'Product catalog':
    list_products_screen()
