from __future__ import annotations

import os
import uuid

import requests
import streamlit as st

API_URL = os.getenv("STI_API_URL", "http://127.0.0.1:8000").rstrip("/")


def api() -> requests.Session:
    if "api_session" not in st.session_state:
        st.session_state.api_session = requests.Session()
    return st.session_state.api_session


def request(method: str, path: str, **kwargs) -> requests.Response:
    headers = kwargs.pop("headers", {})
    headers["X-Request-ID"] = str(uuid.uuid4())
    response = api().request(method, f"{API_URL}{path}", headers=headers, timeout=15, **kwargs)
    if response.status_code == 401:
        st.session_state.authenticated = False
    return response


def authenticate() -> None:
    st.title("Tutor de Equações")
    login, register = st.tabs(["Entrar", "Criar conta"])
    with login:
        with st.form("login"):
            email = st.text_input("E-mail")
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar")
        if submitted:
            response = request(
                "POST", "/v1/auth/login", data={"username": email, "password": password}
            )
            if response.is_success:
                st.session_state.authenticated = True
                st.rerun()
            st.error("Credenciais inválidas.")
    with register:
        with st.form("register"):
            email = st.text_input("E-mail", key="register-email")
            password = st.text_input("Senha", type="password", key="register-password")
            submitted = st.form_submit_button("Criar conta")
        if submitted:
            response = request(
                "POST", "/v1/auth/register", json={"email": email, "password": password}
            )
            if response.is_success:
                st.success("Conta criada. Entre para continuar.")
            else:
                st.error(response.json().get("detail", "Não foi possível criar a conta."))


def new_attempt() -> None:
    problem = request("GET", "/v1/problems/next")
    if not problem.is_success:
        st.error("Não foi possível obter um problema.")
        return
    item = problem.json()
    attempt = request(
        "POST",
        "/v1/attempts",
        json={"problem_id": item["id"]},
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    if attempt.is_success:
        st.session_state.attempt = attempt.json()
        st.session_state.hints = []


def tutor() -> None:
    st.title("Tutor de Equações de Primeiro Grau")
    if st.button("Sair"):
        request("POST", "/v1/auth/logout")
        st.session_state.clear()
        st.rerun()
    if "attempt" not in st.session_state:
        new_attempt()
    attempt = st.session_state.get("attempt")
    if not attempt:
        return
    problem = attempt["problem"]
    st.subheader(problem["equation"])
    st.caption(f"Resolva para {problem['variable']} · dificuldade {problem['difficulty']}")
    with st.form("answer"):
        answer = st.text_input("Sua resposta")
        submitted = st.form_submit_button("Enviar")
    if submitted:
        response = request(
            "POST",
            f"/v1/attempts/{attempt['id']}/submissions",
            json={"answer": answer},
            headers={"Idempotency-Key": str(uuid.uuid4())},
        )
        if response.is_success:
            result = response.json()
            if result["correct"]:
                st.success(f"Correto! Você ganhou {result['points']} pontos.")
            else:
                st.error("Resposta incorreta. Tente novamente.")
        else:
            st.error("Use uma resposta numérica ou fracionária válida.")
    hint_col, next_col, explanation_col = st.columns(3)
    if hint_col.button("Obter dica"):
        response = request("POST", f"/v1/attempts/{attempt['id']}/hints")
        if response.is_success:
            st.session_state.hints.append(response.json()["text"])
        else:
            st.info("Não há mais dicas disponíveis.")
    if next_col.button("Novo problema"):
        new_attempt()
        st.rerun()
    if explanation_col.button("Explicação"):
        response = request("POST", f"/v1/attempts/{attempt['id']}/explanation")
        if response.is_success:
            st.info(response.json()["text"])
    for hint in st.session_state.get("hints", []):
        st.info(hint)
    progress = request("GET", "/v1/me/progress")
    if progress.is_success:
        data = progress.json()
        st.divider()
        left, right = st.columns(2)
        left.metric("Problemas resolvidos", data["solved"])
        right.metric("Pontos", data["points"])
        st.bar_chart(data["by_difficulty"])


if not st.session_state.get("authenticated"):
    authenticate()
else:
    tutor()
