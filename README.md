# kworker

[![PyPI version](https://badge.fury.io/py/kworker.svg)](https://badge.fury.io/py/kworker)
[![Python versions](https://img.shields.io/pypi/pyversions/kworker.svg)](https://pypi.org/project/kworker/)
[![License](https://img.shields.io/pypi/l/kworker.svg)](https://pypi.org/project/kworker/)
[![GitHub stars](https://img.shields.io/github/stars/Tinokil/kworker.svg)](https://github.com/Tinokil/kworker/stargazers)
[![GitHub release date](https://img.shields.io/github/release-date/Tinokil/kworker.svg)](https://github.com/Tinokil/kworker/releases)


## Зачем нужен kworker
Предоставить удобное взаимодействие с API фриланс биржи kwork.ru

## Как установить kworker
`python -m pip install kworker`

## Начало работы с kworker
```python
import asyncio
from kworker import KworkAPI

async def main():
    try:
        client = KworkAPI(login="example@email.com", password="123456", phone_last='1234')
        # Получение информации о себе
        me = await client.get_me()
        print(f"Авторизован: {me.username} (ID: {me.id})")
        # Отправка своего запроса
        await client.request(method="post", api_method="user", id="10101", token=await client.token)
    finally:
        await client.close()

asyncio.run(main())
```

## Поддержка  
- **Баги и предложения**: [GitHub Issues](https://github.com/Tinokil/kworker/issues)  
- **Telegram**: [@maaks11](https://t.me/maaks11)
