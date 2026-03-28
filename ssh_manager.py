#!/usr/bin/env python3
"""
SSH Manager — интерактивное TUI-меню для управления SSH на Ubuntu 24.04
https://github.com/
"""

import os
import sys
import subprocess
import shutil
import pwd
import grp
import re
import time
import socket
import getpass
from pathlib import Path

# ─── Цвета ────────────────────────────────────────────────────────────────────

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
RESET  = "\033[0m"

def ok(msg):    print(f"{GREEN}✓ {msg}{RESET}")
def err(msg):   print(f"{RED}✗ {msg}{RESET}")
def warn(msg):  print(f"{YELLOW}⚠ {msg}{RESET}")
def info(msg):  print(f"{CYAN}→ {msg}{RESET}")
def bold(msg):  print(f"{BOLD}{msg}{RESET}")

# ─── Утилиты ──────────────────────────────────────────────────────────────────

SSHD_CONFIG     = "/etc/ssh/sshd_config"
SSHD_CONFIG_BAK = "/etc/ssh/sshd_config.bak"

def clear():
    os.system("clear")

def pause():
    input(f"\n{DIM}Нажми Enter для продолжения...{RESET}")

def confirm(question: str) -> bool:
    ans = input(f"{YELLOW}{question} (y/n): {RESET}").strip().lower()
    return ans == "y"

def run(cmd: list[str], check=True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)

def is_root() -> bool:
    return os.geteuid() == 0

def require_root():
    if not is_root():
        err("Требуются права root. Запусти через sudo.")
        sys.exit(1)

def sshd_config_get(key: str) -> str:
    """Получить значение параметра из sshd_config (последнее вхождение)."""
    value = ""
    try:
        with open(SSHD_CONFIG) as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].lower() == key.lower():
                    value = parts[1]
    except Exception:
        pass
    return value

def sshd_config_set(key: str, value: str):
    """Установить/заменить параметр в sshd_config."""
    backup_config()
    with open(SSHD_CONFIG) as f:
        lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            new_lines.append(line)
            continue
        parts = stripped.split(None, 1)
        if parts and parts[0].lower() == key.lower():
            if not found:
                new_lines.append(f"{key} {value}\n")
                found = True
            # пропускаем дубликаты
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"\n{key} {value}\n")

    with open(SSHD_CONFIG, "w") as f:
        f.writelines(new_lines)

def backup_config():
    if not os.path.exists(SSHD_CONFIG_BAK):
        shutil.copy2(SSHD_CONFIG, SSHD_CONFIG_BAK)
        info(f"Резервная копия создана: {SSHD_CONFIG_BAK}")

def validate_sshd() -> bool:
    result = run(["sshd", "-t"], check=False)
    return result.returncode == 0

def restart_sshd() -> bool:
    if not validate_sshd():
        err("Конфиг содержит ошибки (sshd -t). Рестарт отменён.")
        return False
    result = run(["systemctl", "restart", "ssh"], check=False)
    if result.returncode != 0:
        result = run(["systemctl", "restart", "sshd"], check=False)
    return result.returncode == 0

def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0

def get_system_users() -> list[str]:
    """Все пользователи с домашней директорией в /home."""
    users = []
    for pw in pwd.getpwall():
        if pw.pw_dir.startswith("/home") and pw.pw_shell not in ("/usr/sbin/nologin", "/bin/false"):
            users.append(pw.pw_name)
    return sorted(users)

def get_authorized_keys_path(username: str) -> Path:
    try:
        pw = pwd.getpwnam(username)
        return Path(pw.pw_dir) / ".ssh" / "authorized_keys"
    except KeyError:
        return None

def read_authorized_keys(username: str) -> list[str]:
    path = get_authorized_keys_path(username)
    if path is None or not path.exists():
        return []
    with open(path) as f:
        return [l.rstrip("\n") for l in f if l.strip() and not l.startswith("#")]

def write_authorized_keys(username: str, keys: list[str]):
    path = get_authorized_keys_path(username)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("\n".join(keys) + "\n" if keys else "")
    # Исправляем права
    pw = pwd.getpwnam(username)
    os.chown(path.parent, pw.pw_uid, pw.pw_gid)
    os.chmod(path.parent, 0o700)
    os.chown(path, pw.pw_uid, pw.pw_gid)
    os.chmod(path, 0o600)

def is_valid_ssh_key(key: str) -> bool:
    parts = key.split()
    if len(parts) < 2:
        return False
    valid_types = {"ssh-rsa", "ssh-ed25519", "ssh-dss", "ecdsa-sha2-nistp256",
                   "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521", "sk-ssh-ed25519@openssh.com"}
    return parts[0] in valid_types

def user_has_sudo(username: str) -> bool:
    try:
        g = grp.getgrnam("sudo")
        return username in g.gr_mem
    except KeyError:
        return False

def get_current_port() -> int:
    val = sshd_config_get("Port")
    try:
        return int(val)
    except (ValueError, TypeError):
        return 22

# ─── Шапка ────────────────────────────────────────────────────────────────────

def header(title: str = "SSH MANAGER"):
    clear()
    width = 42
    print(f"{CYAN}{BOLD}{'═' * width}{RESET}")
    print(f"{CYAN}{BOLD}  {title.center(width - 4)}{RESET}")
    print(f"{CYAN}{BOLD}{'═' * width}{RESET}")
    print()

# ─── 1. Управление ключами ────────────────────────────────────────────────────

def menu_keys():
    while True:
        header("УПРАВЛЕНИЕ КЛЮЧАМИ")
        print("  1. Добавить ключ")
        print("  2. Удалить ключ")
        print("  3. Показать ключи")
        print(f"  {DIM}0. Назад{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            keys_add()
        elif choice == "2":
            keys_remove()
        elif choice == "3":
            keys_show()
        elif choice in ("0", "назад", "back"):
            break
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def pick_user(prompt="Пользователь") -> str | None:
    users = get_system_users()
    if not users:
        err("Нет пользователей с домашней директорией в /home.")
        return None
    print(f"\n{BOLD}Доступные пользователи:{RESET}")
    for i, u in enumerate(users, 1):
        print(f"  {i}. {u}")
    raw = input(f"{prompt} (номер или имя): ").strip()
    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(users):
            return users[idx]
        err("Нет такого номера.")
        return None
    if raw in users:
        return raw
    err(f"Пользователь '{raw}' не найден.")
    return None

def keys_add():
    header("ДОБАВИТЬ КЛЮЧ")
    username = pick_user()
    if not username:
        pause()
        return

    print(f"\n{BOLD}Источник ключа:{RESET}")
    print("  1. Вставить вручную")
    print("  2. Указать файл")
    src = input("Выбор: ").strip()

    if src == "1":
        key = input("Вставь SSH-ключ: ").strip()
    elif src == "2":
        fpath = input("Путь к файлу: ").strip()
        try:
            key = Path(fpath).read_text().strip()
        except Exception as e:
            err(f"Не удалось прочитать файл: {e}")
            pause()
            return
    else:
        warn("Отмена.")
        return

    if not is_valid_ssh_key(key):
        err("Неверный формат SSH-ключа.")
        pause()
        return

    existing = read_authorized_keys(username)
    if key in existing:
        warn("Этот ключ уже добавлен.")
        pause()
        return

    existing.append(key)
    write_authorized_keys(username, existing)
    ok(f"Ключ добавлен для пользователя '{username}'.")
    pause()

def keys_remove():
    header("УДАЛИТЬ КЛЮЧ")
    username = pick_user()
    if not username:
        pause()
        return

    keys = read_authorized_keys(username)
    if not keys:
        warn(f"У '{username}' нет авторизованных ключей.")
        pause()
        return

    print(f"\n{BOLD}Ключи пользователя {username}:{RESET}")
    for i, k in enumerate(keys, 1):
        short = k[:60] + "..." if len(k) > 60 else k
        print(f"  {i}. {short}")

    raw = input("\nНомер ключа для удаления (0 — отмена): ").strip()
    if raw == "0":
        return
    if not raw.isdigit() or not (1 <= int(raw) <= len(keys)):
        err("Неверный номер.")
        pause()
        return

    idx = int(raw) - 1
    removed = keys.pop(idx)
    short = removed[:60] + "..." if len(removed) > 60 else removed
    if confirm(f"Удалить ключ: {short}?"):
        write_authorized_keys(username, keys)
        ok("Ключ удалён.")
    else:
        info("Отмена.")
    pause()

def keys_show():
    header("ПОКАЗАТЬ КЛЮЧИ")
    username = pick_user()
    if not username:
        pause()
        return

    keys = read_authorized_keys(username)
    if not keys:
        warn(f"У '{username}' нет авторизованных ключей.")
    else:
        print(f"\n{BOLD}Ключи пользователя {username} ({len(keys)} шт.):{RESET}\n")
        for i, k in enumerate(keys, 1):
            parts = k.split()
            comment = parts[2] if len(parts) >= 3 else ""
            ktype   = parts[0] if parts else ""
            short   = parts[1][:20] + "..." if len(parts) > 1 else ""
            print(f"  {i}. {CYAN}{ktype}{RESET} {short} {DIM}{comment}{RESET}")
    pause()

# ─── 2. Пользователи ──────────────────────────────────────────────────────────

def menu_users():
    while True:
        header("ПОЛЬЗОВАТЕЛИ")
        print("  1. Создать пользователя")
        print("  2. Удалить пользователя")
        print("  3. Выдать sudo")
        print("  4. Убрать sudo")
        print(f"  {DIM}0. Назад{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            users_create()
        elif choice == "2":
            users_delete()
        elif choice == "3":
            users_sudo_add()
        elif choice == "4":
            users_sudo_remove()
        elif choice in ("0", "назад"):
            break
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def users_create():
    header("СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ")
    name = input("Имя пользователя: ").strip()
    if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', name):
        err("Недопустимое имя пользователя.")
        pause()
        return
    try:
        pwd.getpwnam(name)
        err(f"Пользователь '{name}' уже существует.")
        pause()
        return
    except KeyError:
        pass

    password = getpass.getpass("Пароль: ")
    if not password:
        err("Пароль не может быть пустым.")
        pause()
        return
    password2 = getpass.getpass("Повтори пароль: ")
    if password != password2:
        err("Пароли не совпадают.")
        pause()
        return

    result = run(["useradd", "-m", "-s", "/bin/bash", name], check=False)
    if result.returncode != 0:
        err(f"Ошибка создания пользователя: {result.stderr.strip()}")
        pause()
        return

    # Установка пароля
    proc = subprocess.run(
        ["chpasswd"],
        input=f"{name}:{password}",
        capture_output=True, text=True
    )
    if proc.returncode != 0:
        err("Ошибка установки пароля.")
        pause()
        return

    ok(f"Пользователь '{name}' создан.")

    if confirm("Добавить SSH-ключ сейчас?"):
        key = input("Вставь SSH-ключ: ").strip()
        if is_valid_ssh_key(key):
            write_authorized_keys(name, [key])
            ok("SSH-ключ добавлен.")
        else:
            err("Неверный формат ключа. Ключ не добавлен.")

    if confirm("Выдать sudo?"):
        run(["usermod", "-aG", "sudo", name])
        ok(f"Пользователь '{name}' добавлен в группу sudo.")

    pause()

def users_delete():
    header("УДАЛИТЬ ПОЛЬЗОВАТЕЛЯ")
    username = pick_user()
    if not username:
        pause()
        return
    if username == "root":
        err("Нельзя удалить root.")
        pause()
        return
    if not confirm(f"Удалить пользователя '{username}' вместе с домашней директорией?"):
        info("Отмена.")
        pause()
        return
    result = run(["userdel", "-r", username], check=False)
    if result.returncode == 0:
        ok(f"Пользователь '{username}' удалён.")
    else:
        err(f"Ошибка: {result.stderr.strip()}")
    pause()

def users_sudo_add():
    header("ВЫДАТЬ SUDO")
    username = pick_user()
    if not username:
        pause()
        return
    if user_has_sudo(username):
        warn(f"'{username}' уже имеет sudo.")
        pause()
        return
    run(["usermod", "-aG", "sudo", username])
    ok(f"sudo выдан пользователю '{username}'.")
    pause()

def users_sudo_remove():
    header("УБРАТЬ SUDO")
    username = pick_user()
    if not username:
        pause()
        return
    if not user_has_sudo(username):
        warn(f"'{username}' не имеет sudo.")
        pause()
        return
    run(["gpasswd", "-d", username, "sudo"])
    ok(f"sudo убран у '{username}'.")
    pause()

# ─── 3. Настройки SSH ─────────────────────────────────────────────────────────

def menu_ssh():
    while True:
        header("НАСТРОЙКИ SSH")
        port = get_current_port()
        print(f"  {DIM}Текущий порт: {port}{RESET}\n")
        print("  1. Показать текущие настройки")
        print("  2. Изменить порт")
        print("  3. Перезапустить SSH")
        print(f"  {DIM}0. Назад{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            ssh_show_settings()
        elif choice == "2":
            ssh_change_port()
        elif choice == "3":
            ssh_restart()
        elif choice in ("0", "назад"):
            break
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def ssh_show_settings():
    header("ТЕКУЩИЕ НАСТРОЙКИ SSH")
    keys_to_show = [
        "Port", "PermitRootLogin", "PasswordAuthentication",
        "PubkeyAuthentication", "AuthorizedKeysFile",
        "UsePAM", "X11Forwarding", "MaxAuthTries",
    ]
    for key in keys_to_show:
        val = sshd_config_get(key) or f"{DIM}(не задан){RESET}"
        print(f"  {CYAN}{key:<28}{RESET} {val}")
    pause()

def ssh_change_port():
    header("ИЗМЕНИТЬ ПОРТ")
    current = get_current_port()
    info(f"Текущий порт: {current}")
    raw = input("Новый порт (1–65535): ").strip()
    if not raw.isdigit():
        err("Введи число.")
        pause()
        return
    port = int(raw)
    if not (1 <= port <= 65535):
        err("Порт вне допустимого диапазона.")
        pause()
        return
    if port == current:
        warn("Это уже текущий порт.")
        pause()
        return
    if not port_is_free(port):
        err(f"Порт {port} уже занят.")
        pause()
        return

    warn(f"Смена порта с {current} на {port}.")
    warn("Ты можешь потерять текущий SSH-доступ!")
    if not confirm("Продолжить?"):
        info("Отмена.")
        pause()
        return

    sshd_config_set("Port", str(port))
    if validate_sshd():
        ok(f"Порт изменён на {port}. Перезапусти SSH вручную или через меню.")
    else:
        err("Конфиг содержит ошибки. Откатываю.")
        shutil.copy2(SSHD_CONFIG_BAK, SSHD_CONFIG)
    pause()

def ssh_restart():
    header("ПЕРЕЗАПУСК SSH")
    warn("Перезапускаю SSH...")
    if restart_sshd():
        ok("SSH успешно перезапущен.")
    else:
        err("Ошибка перезапуска SSH.")
    pause()

# ─── 4. Безопасность ──────────────────────────────────────────────────────────

def menu_security():
    while True:
        header("БЕЗОПАСНОСТЬ")
        root_login = sshd_config_get("PermitRootLogin") or "yes"
        pass_auth  = sshd_config_get("PasswordAuthentication") or "yes"
        print(f"  {DIM}PermitRootLogin:        {root_login}{RESET}")
        print(f"  {DIM}PasswordAuthentication: {pass_auth}{RESET}\n")
        print("  1. Запретить вход root")
        print("  2. Разрешить вход root")
        print("  3. Отключить вход по паролю")
        print("  4. Включить вход по паролю")
        print(f"  {DIM}0. Назад{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            sec_deny_root()
        elif choice == "2":
            sec_allow_root()
        elif choice == "3":
            sec_disable_password()
        elif choice == "4":
            sec_enable_password()
        elif choice in ("0", "назад"):
            break
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def _apply_and_restart(key, value, success_msg):
    sshd_config_set(key, value)
    if not validate_sshd():
        err("Конфиг содержит ошибки. Откатываю.")
        shutil.copy2(SSHD_CONFIG_BAK, SSHD_CONFIG)
        pause()
        return
    if restart_sshd():
        ok(success_msg)
    else:
        err("SSH не удалось перезапустить.")
    pause()

def sec_deny_root():
    header("ЗАПРЕТИТЬ ВХОД ROOT")
    if not confirm("Запретить вход root по SSH?"):
        return
    _apply_and_restart("PermitRootLogin", "no", "Вход root запрещён.")

def sec_allow_root():
    header("РАЗРЕШИТЬ ВХОД ROOT")
    if not confirm("Разрешить вход root по SSH?"):
        return
    _apply_and_restart("PermitRootLogin", "yes", "Вход root разрешён.")

def sec_disable_password():
    header("ОТКЛЮЧИТЬ ВХОД ПО ПАРОЛЮ")
    # Проверка: есть ли у кого-то SSH-ключи
    users_with_keys = []
    for u in get_system_users():
        if read_authorized_keys(u):
            users_with_keys.append(u)

    if not users_with_keys:
        warn("Нет ни одного пользователя с SSH-ключом!")
        err("Отключение пароля заблокирует ВЕСЬ доступ к серверу.")
        if not confirm("Ты ТОЧНО хочешь продолжить и рискуешь потерять доступ?"):
            info("Отмена — правильное решение.")
            pause()
            return
    else:
        info(f"Пользователи с ключами: {', '.join(users_with_keys)}")
        if not confirm("Отключить вход по паролю?"):
            return

    _apply_and_restart("PasswordAuthentication", "no", "Вход по паролю отключён.")

def sec_enable_password():
    header("ВКЛЮЧИТЬ ВХОД ПО ПАРОЛЮ")
    if not confirm("Включить вход по паролю?"):
        return
    _apply_and_restart("PasswordAuthentication", "yes", "Вход по паролю включён.")

# ─── 5. Откат ─────────────────────────────────────────────────────────────────

def menu_restore():
    while True:
        header("ОТКАТ")
        bak_exists = os.path.exists(SSHD_CONFIG_BAK)
        if bak_exists:
            mtime = os.path.getmtime(SSHD_CONFIG_BAK)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
            info(f"Резервная копия от {ts}")
        else:
            warn("Резервной копии нет.")
        print()
        print("  1. Восстановить sshd_config из резервной копии")
        print("  2. Включить пароль и root (аварийный сброс)")
        print(f"  {DIM}0. Назад{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            restore_config()
        elif choice == "2":
            restore_emergency()
        elif choice in ("0", "назад"):
            break
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def restore_config():
    header("ВОССТАНОВИТЬ КОНФИГ")
    if not os.path.exists(SSHD_CONFIG_BAK):
        err("Резервная копия не найдена.")
        pause()
        return
    if not confirm("Восстановить sshd_config из резервной копии и перезапустить SSH?"):
        return
    shutil.copy2(SSHD_CONFIG_BAK, SSHD_CONFIG)
    if restart_sshd():
        ok("Конфиг восстановлен, SSH перезапущен.")
    else:
        err("SSH не удалось перезапустить после восстановления.")
    pause()

def restore_emergency():
    header("АВАРИЙНЫЙ СБРОС")
    warn("Это включит PasswordAuthentication yes и PermitRootLogin yes!")
    if not confirm("Продолжить?"):
        return
    sshd_config_set("PasswordAuthentication", "yes")
    sshd_config_set("PermitRootLogin", "yes")
    if validate_sshd() and restart_sshd():
        ok("Доступ восстановлен: пароль и root разрешены.")
    else:
        err("Не удалось применить изменения.")
    pause()

# ─── 6. Безопасная настройка (мастер) ────────────────────────────────────────

def menu_secure_setup():
    """
    Мастер: создать нового пользователя → добавить ключ → сменить порт →
    дать время проверить → отключить root и пароль.
    """
    header("МАСТЕР БЕЗОПАСНОЙ НАСТРОЙКИ")
    print(f"""  {BOLD}Этот мастер поможет безопасно настроить SSH:{RESET}

  1. Создаст нового пользователя с SSH-ключом
  2. (Опционально) Сменит порт
  3. Даст время проверить доступ из нового окна
  4. Отключит root-вход и вход по паролю
""")
    if not confirm("Начать?"):
        return

    # Шаг 1: Пользователь
    header("ШАГ 1: СОЗДАТЬ ПОЛЬЗОВАТЕЛЯ")
    name = input("Имя нового пользователя: ").strip()
    if not re.match(r'^[a-z_][a-z0-9_-]{0,31}$', name):
        err("Недопустимое имя.")
        pause()
        return
    try:
        pwd.getpwnam(name)
        warn(f"Пользователь '{name}' уже существует. Будет использован он.")
    except KeyError:
        password = getpass.getpass("Пароль: ")
        password2 = getpass.getpass("Повтори пароль: ")
        if password != password2:
            err("Пароли не совпадают.")
            pause()
            return
        run(["useradd", "-m", "-s", "/bin/bash", name])
        proc = subprocess.run(["chpasswd"], input=f"{name}:{password}",
                              capture_output=True, text=True)
        if proc.returncode != 0:
            err("Ошибка установки пароля.")
            pause()
            return
        run(["usermod", "-aG", "sudo", name])
        ok(f"Пользователь '{name}' создан с sudo.")

    # SSH-ключ
    key = input("\nSSH-ключ для нового пользователя (Enter — пропустить): ").strip()
    if key:
        if is_valid_ssh_key(key):
            write_authorized_keys(name, [key])
            ok("SSH-ключ добавлен.")
        else:
            err("Неверный формат ключа. Ключ не добавлен.")
            if not confirm("Продолжить без ключа (опасно)?"):
                pause()
                return

    # Шаг 2: Порт
    header("ШАГ 2: СМЕНА ПОРТА (ОПЦИОНАЛЬНО)")
    current_port = get_current_port()
    info(f"Текущий порт: {current_port}")
    raw = input("Новый порт (Enter — оставить текущий): ").strip()
    new_port = current_port
    if raw:
        if raw.isdigit() and 1 <= int(raw) <= 65535:
            if port_is_free(int(raw)):
                sshd_config_set("Port", raw)
                new_port = int(raw)
                ok(f"Порт будет изменён на {new_port}.")
            else:
                err(f"Порт {raw} занят. Оставляю текущий.")
        else:
            err("Недопустимый порт. Оставляю текущий.")

    if not validate_sshd():
        err("Конфиг с ошибками. Откатываю.")
        shutil.copy2(SSHD_CONFIG_BAK, SSHD_CONFIG)
        pause()
        return

    restart_sshd()
    ok("SSH перезапущен с новыми настройками.")

    # Шаг 3: Пауза для проверки
    header("ШАГ 3: ПРОВЕРЬ ДОСТУП")
    print(f"""  {YELLOW}Открой НОВОЕ окно терминала и проверь подключение:{RESET}

  {BOLD}ssh -p {new_port} {name}@<IP_сервера>{RESET}

  Убедись что:
  {GREEN}✓{RESET} Ты можешь войти под новым пользователем
  {GREEN}✓{RESET} sudo работает
  {GREEN}✓{RESET} Ты не закрыл этот сеанс

  {RED}НЕ закрывай это окно до подтверждения!{RESET}
""")
    if not confirm("Доступ проверен и работает?"):
        warn("Мудро. Настройки безопасности НЕ применены.")
        pause()
        return

    # Шаг 4: Применить ограничения
    header("ШАГ 4: ПРИМЕНЯЕМ ОГРАНИЧЕНИЯ")
    sshd_config_set("PermitRootLogin", "no")
    sshd_config_set("PasswordAuthentication", "no")

    if validate_sshd() and restart_sshd():
        ok("PermitRootLogin → no")
        ok("PasswordAuthentication → no")
        ok("SSH перезапущен.")
        print(f"\n  {GREEN}{BOLD}Сервер защищён!{RESET}")
    else:
        err("Ошибка. Откатываю.")
        shutil.copy2(SSHD_CONFIG_BAK, SSHD_CONFIG)
        restart_sshd()
    pause()

# ─── Главное меню ─────────────────────────────────────────────────────────────

def menu_main():
    while True:
        header()
        print(f"  {BOLD}1.{RESET} Управление ключами")
        print(f"  {BOLD}2.{RESET} Пользователи")
        print(f"  {BOLD}3.{RESET} Настройки SSH")
        print(f"  {BOLD}4.{RESET} Безопасность")
        print(f"  {BOLD}5.{RESET} Откат")
        print(f"  {GREEN}{BOLD}6.{RESET}{GREEN} Мастер безопасной настройки{RESET}")
        print(f"  {DIM}0. Выход{RESET}")
        print()
        choice = input("Выбор: ").strip()

        if choice == "1":
            menu_keys()
        elif choice == "2":
            menu_users()
        elif choice == "3":
            menu_ssh()
        elif choice == "4":
            menu_security()
        elif choice == "5":
            menu_restore()
        elif choice == "6":
            menu_secure_setup()
        elif choice in ("0", "q", "выход", "exit"):
            clear()
            print(f"{DIM}До свидания.{RESET}\n")
            sys.exit(0)
        else:
            warn("Неверный выбор.")
            time.sleep(0.8)

def main():
    require_root()
    try:
        menu_main()
    except KeyboardInterrupt:
        clear()
        print(f"\n{DIM}Прервано. До свидания.{RESET}\n")
        sys.exit(0)

if __name__ == "__main__":
    main()
