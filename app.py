import streamlit as st
import requests
import json
import uuid
from datetime import datetime
import time
import sqlite3
from pathlib import Path

# Page configuration
st.set_page_config(
    page_title="BIPP Analytics",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Minimal CSS - avoiding sidebar interference
st.markdown("""
<style>
    /* Main content styling only */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
        max-width: none;
    }
    
    .main-header {
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid #e9ecef;
    }
    
    .app-title {
        font-size: 2rem;
        font-weight: 300;
        color: #2c3e50;
        margin: 0;
        line-height: 1.2;
    }
    
    .app-subtitle {
        font-size: 0.9rem;
        color: #6c757d;
        margin: 0.25rem 0 0 0;
        font-weight: 400;
    }
    
    /* Status indicator */
    .status-indicator {
        display: inline-flex;
        align-items: center;
        gap: 0.5rem;
        font-size: 0.85rem;
        padding: 0.25rem 0;
    }
    
    .status-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        flex-shrink: 0;
    }
    
    .status-healthy .status-dot { background-color: #28a745; }
    .status-offline .status-dot { background-color: #dc3545; }
    .status-unknown .status-dot { background-color: #6c757d; }
    
    /* Chat interface */
    .chat-container {
        background: #ffffff;
        border-radius: 8px;
        border: 1px solid #e9ecef;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    
    .chat-header {
        font-size: 1.1rem;
        font-weight: 500;
        color: #495057;
        margin-bottom: 1rem;
        padding-bottom: 0.5rem;
        border-bottom: 1px solid #f8f9fa;
    }
    
    /* Custom spinner */
    .custom-spinner {
        display: inline-flex;
        align-items: center;
        gap: 0.75rem;
        padding: 1rem;
        background: #f8f9fa;
        border-radius: 6px;
        border: 1px solid #e9ecef;
        margin: 0.5rem 0;
    }
    
    .spinner {
        width: 20px;
        height: 20px;
        border: 2px solid #e9ecef;
        border-top: 2px solid #007bff;
        border-radius: 50%;
        animation: spin 1s linear infinite;
    }
    
    @keyframes spin {
        0% { transform: rotate(0deg); }
        100% { transform: rotate(360deg); }
    }
    
    .spinner-text {
        color: #6c757d;
        font-size: 0.9rem;
        font-style: italic;
    }
    
    /* Minimal sidebar styling - no interference */
    .sidebar-content {
        padding: 1rem 0;
    }
    
    .sidebar-section {
        margin-bottom: 2rem;
        padding-bottom: 1rem;
        border-bottom: 1px solid #f0f0f0;
    }
    
    .sidebar-section:last-child {
        border-bottom: none;
    }
    
    .sidebar-title {
        font-size: 0.9rem;
        font-weight: 600;
        color: #6c757d;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 0.5rem;
    }
    
    /* Hide Streamlit branding only */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# API endpoints
API_BASE_URL = "http://44.218.47.211:8000"
SQL_QUERY_ENDPOINT = f"{API_BASE_URL}/sql-query"
HEALTH_ENDPOINT = f"{API_BASE_URL}/health"
CLEAR_SESSION_ENDPOINT = f"{API_BASE_URL}/clear-session"
MODELS_ENDPOINT = f"{API_BASE_URL}/models"

# Local storage
STORAGE_DIR = Path("streamlit_storage")
STORAGE_DIR.mkdir(exist_ok=True)
SESSIONS_DB = STORAGE_DIR / "sessions.db"

# Initialize session state
for key, default in [
    ("messages", []),
    ("session_id", str(uuid.uuid4())),
    ("session_name", "Nova Sessão"),
    ("api_status", "unknown"),
    ("available_models", {}),
    ("selected_model", "openai:gpt-4o-mini"),
    ("all_sessions", []),
    ("streaming_response", ""),
    ("is_processing", False)
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Database functions
def init_sessions_db():
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            session_name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES sessions (session_id)
        )
        """
    )
    conn.commit()
    conn.close()

def save_session(session_id: str, session_name: str):
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR REPLACE INTO sessions (session_id, session_name, last_activity)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        """,
        (session_id, session_name)
    )
    conn.commit()
    conn.close()

def save_message(session_id: str, role: str, content: str, timestamp: str):
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO messages (session_id, role, content, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, role, content, timestamp)
    )
    cursor.execute(
        """
        UPDATE sessions SET last_activity = CURRENT_TIMESTAMP
        WHERE session_id = ?
        """,
        (session_id,)
    )
    conn.commit()
    conn.close()

def load_session_messages(session_id: str):
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT role, content, timestamp FROM messages
        WHERE session_id = ?
        ORDER BY created_at ASC
        """,
        (session_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    return [{"role": r[0], "content": r[1], "timestamp": r[2]} for r in rows]

def get_all_sessions():
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT session_id, session_name, last_activity
        FROM sessions
        ORDER BY last_activity DESC
        """
    )
    rows = cursor.fetchall()
    conn.close()
    return [
        {"session_id": r[0], "session_name": r[1], "last_activity": r[2]}
        for r in rows
    ]

def delete_session(session_id: str):
    conn = sqlite3.connect(SESSIONS_DB)
    cursor = conn.cursor()
    cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
    cursor.execute('DELETE FROM sessions WHERE session_id = ?', (session_id,))
    conn.commit()
    conn.close()

def switch_session(session_id: str, session_name: str):
    st.session_state.session_id = session_id
    st.session_state.session_name = session_name
    st.session_state.messages = load_session_messages(session_id)

# API helpers
def check_api_health():
    try:
        res = requests.get(HEALTH_ENDPOINT, timeout=5)
        if res.status_code == 200:
            data = res.json()
            st.session_state.api_status = data.get("status", "unknown")
            return data
        st.session_state.api_status = "offline"
    except requests.exceptions.RequestException:
        st.session_state.api_status = "offline"
    return None

def get_available_models():
    try:
        res = requests.get(MODELS_ENDPOINT, timeout=10)
        if res.status_code == 200:
            data = res.json()
            st.session_state.available_models = data.get("models", {})
            return data
    except requests.exceptions.RequestException:
        pass
    return None

def clear_session_memory():
    try:
        res = requests.post(f"{CLEAR_SESSION_ENDPOINT}/{st.session_state.session_id}")
        if res.status_code == 200:
            return res.json()
        return {"status": "error", "error": f"HTTP {res.status_code}"}
    except requests.exceptions.RequestException as e:
        return {"status": "error", "error": str(e)}

def stream_sql_query_generator(query: str, session_id: str, model_id: str):
    try:
        payload = {"query": query, "session_id": session_id, "model_id": model_id, "stream": True, "debug_mode": False}
        res = requests.post(SQL_QUERY_ENDPOINT, json=payload, stream=True, timeout=300)
        if res.status_code != 200:
            yield {"status": "error", "error": f"HTTP {res.status_code}: {res.text}"}
            return
        for line in res.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                data = json.loads(line[6:])
                yield data
    except requests.exceptions.RequestException as e:
        yield {"status": "error", "error": str(e)}

def display_message(role: str, content: str, timestamp: str = None):
    with st.chat_message(role):
        if timestamp:
            st.caption(timestamp)
        st.markdown(content)

def show_spinner(text: str = "Processando sua consulta..."):
    """Display a custom spinner with text"""
    return st.markdown(f"""
    <div class="custom-spinner">
        <div class="spinner"></div>
        <span class="spinner-text">{text}</span>
    </div>
    """, unsafe_allow_html=True)

def create_new_session():
    new_id = str(uuid.uuid4())
    new_name = f"Sessão {datetime.now().strftime('%d/%m %H:%M')}"
    save_session(new_id, new_name)
    switch_session(new_id, new_name)
    return new_id, new_name

# Sidebar content
def render_sidebar():
    with st.sidebar:
        st.markdown('<div class="sidebar-content">', unsafe_allow_html=True)
        
        # API Status Section
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-title">Status da API</div>', unsafe_allow_html=True)
        
        status_class = f"status-{st.session_state.api_status}"
        status_texts = {"healthy": "Online", "offline": "Offline", "unknown": "Verificando"}
        status_text = status_texts.get(st.session_state.api_status, "Desconhecido")
        
        st.markdown(f'''
        <div class="status-indicator {status_class}">
            <div class="status-dot"></div>
            <span>{status_text}</span>
        </div>
        ''', unsafe_allow_html=True)
        
        if st.button("Verificar API", key="check_api", disabled=st.session_state.is_processing):
            check_api_health()
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Model Selection Section
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-title">Configurações</div>', unsafe_allow_html=True)
        
        if not st.session_state.available_models:
            get_available_models()
        
        if st.session_state.available_models:
            model_options = []
            for provider, models in st.session_state.available_models.items():
                for model in models:
                    model_options.append(f"{provider}:{model}")
            
            current_index = 0
            if st.session_state.selected_model in model_options:
                current_index = model_options.index(st.session_state.selected_model)
            
            selected_model = st.selectbox(
                "Modelo de IA",
                model_options,
                index=current_index,
                key="model_selector",
                disabled=st.session_state.is_processing
            )
            st.session_state.selected_model = selected_model
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Session Management Section
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-title">Sessões</div>', unsafe_allow_html=True)
        
        # New session button
        if st.button("Nova Sessão", key="new_session", disabled=st.session_state.is_processing):
            create_new_session()
            st.rerun()
        
        # Session list
        if st.session_state.all_sessions:
            st.markdown("**Sessões Ativas:**")
            for session in st.session_state.all_sessions:
                is_current = session['session_id'] == st.session_state.session_id
                
                col1, col2 = st.columns([3, 1])
                with col1:
                    button_label = f"{session['session_name']}"
                    if len(button_label) > 20:
                        button_label = button_label[:17] + "..."
                    
                    if st.button(
                        button_label,
                        key=f"session_{session['session_id']}",
                        disabled=is_current or st.session_state.is_processing,
                        help=f"ID: {session['session_id'][:8]}...\nÚltima atividade: {session['last_activity']}"
                    ):
                        switch_session(session['session_id'], session['session_name'])
                        st.rerun()
                
                with col2:
                    if not is_current and len(st.session_state.all_sessions) > 1:
                        if st.button(
                            "×", 
                            key=f"delete_{session['session_id']}", 
                            help="Deletar sessão",
                            disabled=st.session_state.is_processing
                        ):
                            delete_session(session['session_id'])
                            st.session_state.all_sessions = get_all_sessions()
                            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Session Actions Section
        st.markdown('<div class="sidebar-section">', unsafe_allow_html=True)
        st.markdown('<div class="sidebar-title">Ações da Sessão</div>', unsafe_allow_html=True)
        
        # Rename session
        new_name = st.text_input(
            "Renomear sessão",
            value=st.session_state.session_name,
            key="rename_input",
            disabled=st.session_state.is_processing
        )
        
        if st.button("Salvar Nome", key="save_name", disabled=st.session_state.is_processing):
            if new_name and new_name != st.session_state.session_name:
                st.session_state.session_name = new_name
                save_session(st.session_state.session_id, new_name)
                st.success("Nome atualizado!")
                time.sleep(1)
                st.rerun()
        
        # Clear actions
        if st.button("Limpar Chat", key="clear_chat", disabled=st.session_state.is_processing):
            conn = sqlite3.connect(SESSIONS_DB)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM messages WHERE session_id = ?', (st.session_state.session_id,))
            conn.commit()
            conn.close()
            st.session_state.messages = []
            st.success("Chat limpo!")
            time.sleep(1)
            st.rerun()
        
        st.markdown('</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# Main content
def render_main_content():
    # Header
    st.markdown('<div class="main-header">', unsafe_allow_html=True)
    st.markdown('<h1 class="app-title">BIPP Analytics</h1>', unsafe_allow_html=True)
    st.markdown('<p class="app-subtitle">Análise inteligente de dados com SQL</p>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Chat interface
    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
    current_session_name = st.session_state.session_name
    if len(current_session_name) > 50:
        current_session_name = current_session_name[:47] + "..."
    
    st.markdown(f'<div class="chat-header">Chat: {current_session_name}</div>', unsafe_allow_html=True)
    
    # Load and display messages
    if not st.session_state.messages:
        st.session_state.messages = load_session_messages(st.session_state.session_id)
    
    # Display existing messages
    for msg in st.session_state.messages:
        display_message(msg['role'], msg['content'], msg.get('timestamp'))
    
    st.markdown('</div>', unsafe_allow_html=True)
    
    # Chat input
    chat_disabled = st.session_state.api_status != "healthy" or st.session_state.is_processing
    if st.session_state.api_status != "healthy":
        st.warning("Verifique a conexão para continuar.")
    
    if prompt := st.chat_input(
        "Digite sua pergunta sobre dados da BIPP...", 
        disabled=chat_disabled
    ):
        # Set processing state
        st.session_state.is_processing = True
        
        timestamp = datetime.now().strftime("%H:%M:%S")
        user_msg = {"role": "user", "content": prompt, "timestamp": timestamp}
        st.session_state.messages.append(user_msg)
        save_message(st.session_state.session_id, 'user', prompt, timestamp)
        display_message('user', prompt, timestamp)

        assistant_ts = datetime.now().strftime("%H:%M:%S")
        st.session_state.streaming_response = ""
        
        with st.chat_message("assistant"):
            st.caption(assistant_ts)
            
            # Show spinner while processing
            spinner_container = st.empty()
            with spinner_container.container():
                show_spinner("Processando sua consulta...")
            
            # Container for the actual response
            response_container = st.empty()
            
            try:
                response_received = False
                for chunk in stream_sql_query_generator(prompt, st.session_state.session_id, st.session_state.selected_model):
                    if chunk.get('status') == 'processing':
                        # Update spinner text with more specific message if available
                        processing_msg = chunk.get('message', 'Processando...')
                        spinner_container.empty()
                        with spinner_container.container():
                            show_spinner(processing_msg)
                        time.sleep(0.1)
                    elif chunk.get('status') == 'completed':
                        content = chunk.get('reasoning', 'Nenhuma resposta recebida')
                        spinner_container.empty()  # Remove spinner
                        response_container.markdown(content)
                        assistant_msg = {"role": "assistant", "content": content, "timestamp": assistant_ts}
                        st.session_state.messages.append(assistant_msg)
                        save_message(st.session_state.session_id, 'assistant', content, assistant_ts)
                        response_received = True
                        break
                    elif chunk.get('status') == 'error':
                        err = f"**Erro:** {chunk.get('error', 'Erro desconhecido')}"
                        spinner_container.empty()  # Remove spinner
                        response_container.error(err)
                        save_message(st.session_state.session_id, 'assistant', err, assistant_ts)
                        response_received = True
                        break
                
                # If no response was received, show timeout message
                if not response_received:
                    spinner_container.empty()
                    timeout_msg = "**Timeout:** A consulta demorou muito para responder."
                    response_container.error(timeout_msg)
                    save_message(st.session_state.session_id, 'assistant', timeout_msg, assistant_ts)
                    
            except Exception as e:
                err = f"**Erro inesperado:** {str(e)}"
                spinner_container.empty()  # Remove spinner
                response_container.error(err)
                save_message(st.session_state.session_id, 'assistant', err, assistant_ts)
            
            finally:
                # Reset processing state
                st.session_state.is_processing = False
        
        time.sleep(0.5)
        st.rerun()

# Main app
def main():
    init_sessions_db()
    save_session(st.session_state.session_id, st.session_state.session_name)
    st.session_state.all_sessions = get_all_sessions()
    
    # Check if we have any sessions, create one if not
    if not st.session_state.all_sessions:
        create_new_session()
        st.rerun()
    
    # Render sidebar and main content
    render_sidebar()
    render_main_content()
    
    # Check API status on first load
    if st.session_state.api_status == "unknown":
        check_api_health()

if __name__ == "__main__":
    main()
