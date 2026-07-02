# scannerBnb

Минимальный сканер блоков BNB Smart Chain testnet.

## Файлы

- `scanner.py` - основной скрипт сканера
- `cursor.json` - создается автоматически и хранит последний обработанный блок

## Установка зависимости

```bash
pip install requests
```

## Запуск

```bash
python3 scanner.py
```

По умолчанию используется RPC:

```text
https://data-seed-prebsc-1-s1.bnbchain.org:8545
```

Можно указать другой RPC через переменную окружения:

```bash
RPC_URL="https://your-rpc-url" python3 scanner.py
```
