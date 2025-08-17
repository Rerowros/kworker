import json
import logging
import asyncio
import collections
import aiohttp
from typing import Optional, Union, List, Dict, Callable, Any

from aiohttp_socks import ProxyConnector
from .models import Actor, User, DialogMessage, InboxMessage, Category, Connects, WantWorker
from .exceptions import *

logger = logging.getLogger(__name__)
Handler = collections.namedtuple("Handler", ["func", "text", "on_start", "text_contains"])

class KworkAPI:
    """Клиент для работы с API Kwork.ru
    Аргументы:
        login: Логин аккаунта Kwork
        password: Пароль аккаунта
        proxy: Прокси в формате `socks5://user:pass@host:port`
        phone_last: Последние 4 цифры телефона
    """
    
    # --- Улучшение: константы вынесены на уровень класса для лучшей организации ---
    BASE_URL = "https://api.kwork.ru/{}"
    DEFAULT_API_KEY = "Basic bW9iaWxlX2FwaTpxRnZmUmw3dw=="
    
    def __init__(self, login: str, password: str, proxy: Optional[str] = None, phone_last: Optional[str] = None, api_key: str = DEFAULT_API_KEY):
        self.session = aiohttp.ClientSession(connector=self._create_connector(proxy))
        
        self.login = login
        self.password = password
        self.api_key = api_key
        
        self._token: Optional[str] = None
        self.phone_last = phone_last
        
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _create_connector(self, proxy: Optional[str]) -> Optional[aiohttp.BaseConnector]:
        """Создаёт коннектор для прокси"""
        if proxy:
            try:
                return ProxyConnector.from_url(proxy)
            except ImportError:
                raise KworkConnectionException("Для работы с прокси нужен aiohttp_socks. Установите: pip install aiohttp_socks")
        return None

    @property
    async def token(self) -> str:
        """Токен авторизации (генерируется при первом обращении)"""
        if self._token is None:
            self._token = await self.get_token()
        return self._token

    async def request(self, method: str, api_method: Optional[str] = None, full_url: Optional[str] = None, timeout: int = 10, retried: bool = False, **params) -> Union[Dict, List]:
        """
        Выполняет API-запрос с обработкой ошибок и автоматическим обновлением токена.
        
        Аргументы:
            method (str): HTTP-метод
            api_method (Optional[str]): Название метода API
            full_url (Optional[str]): Полный URL запроса
            retried (bool): [Внутренний] Флаг, указывающий, что это повторный запрос.
            params: Параметры запроса
        Возвращает:
            JSON-ответ запроса
        """
        params = {k: v for k, v in params.items() if v is not None}
        log_params = params.copy()
        if 'password' in log_params: log_params['password'] = '***'
        if 'token' in log_params: log_params['token'] = '***'
        logger.debug(f"Request: {method} {api_method} with params: {log_params}")

        if not (api_method or full_url):
            raise KworkApiException("Необходимо указать api_method или full_url")

        url = full_url or self.BASE_URL.format(api_method)
        request_info = {"method": method, "url": url, "params": log_params}

        try:
            async with self.session.request(method=method, url=url, headers={"Authorization": self.api_key}, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.content_type != "application/json":
                    error_text = await resp.text()
                    raise KworkApiException(f"Недопустимый формат ответа: {error_text}", code=resp.status, request_info=request_info)

                json_response = await resp.json()
                logger.debug(f"Response status: {resp.status}, success: {json_response.get('success')}")

                if not json_response.get("success"):
                    error_msg = json_response.get("error", "Unknown error")
                    error_code = json_response.get("error_code")
                    exc_params = {"code": error_code, "request_info": request_info}

                    if "limit" in error_msg.lower():
                        raise KworkRateLimitException(error_msg, **exc_params)
                # --- Улучшение: теперь это условие инициирует обновление токена ---
                    elif "auth" in error_msg.lower() or "token" in error_msg.lower():
                        raise KworkAuthException(error_msg, **exc_params)
                    else:
                        raise KworkApiException(error_msg, **exc_params)
                return json_response

    # --- Улучшение: логика автоматического обновления токена ---
        except KworkAuthException as e:
            if not retried:
                logger.warning("Authentication error, attempting to refresh token and retry.")
                self._token = None # Invalidate old token
                # Re-add token to params for the retry
                params_for_retry = params.copy()
                params_for_retry['token'] = await self.token
                return await self.request(method, api_method, full_url, timeout, retried=True, **params_for_retry)
            else:
                logger.error("Authentication failed even after token refresh.")
                raise e # Re-raise if retry fails
        except aiohttp.ClientError as e:
            raise KworkConnectionException(f"Ошибка сети: {str(e)}", request_info=request_info) from e
        except json.JSONDecodeError as e:
            raise KworkApiException(f"Недопустимый json: {str(e)}", request_info=request_info) from e
        except Exception as e:
            logger.error("An unexpected error occurred during the request.", exc_info=True)
            raise KworkException(f"Неизвестная ошибка: {str(e)}", request_info=request_info) from e

    async def close(self) -> None:
        """Закрывает HTTP-сессию и сбрасывает токен"""
        if self.session and not self.session.closed:
            await self.session.close()
        self._token = None

    async def get_token(self) -> str:
        """Получает токен авторизации"""
        resp = await self.request(method="post", api_method="signIn", login=self.login, password=self.password, phone_last=self.phone_last)
        token = resp.get("response", {}).get("token")
        if not token:
            raise KworkAuthException("Failed to retrieve token from signIn response.")
        return token

    # --- Улучшение: вспомогательный метод для конкурентной пагинации ---
    async def _fetch_paginated_data(
        self, 
        model: Callable,
        api_method: str, 
        **params
    ) -> List[Any]:
        """
        Асинхронно извлекает все страницы данных, запрашивая их параллельно.
        """
        first_page_data = await self.request(method="post", api_method=api_method, page=1, **params)
        
        paging = first_page_data.get("paging")
        if not paging or paging.get("pages", 1) <= 1:
            return [model(**item) for item in first_page_data.get("response", [])]

        total_pages = paging["pages"]
        results = first_page_data.get("response", [])
        
        tasks = [
            self.request(method="post", api_method=api_method, page=page, **params)
            for page in range(2, total_pages + 1)
        ]
        
        other_pages_responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        for response in other_pages_responses:
            if isinstance(response, Exception):
                logger.error(f"Failed to fetch a page for {api_method}: {response}")
                continue
            results.extend(response.get("response", []))
            
        return [model(**item) for item in results]
        
    async def get_all_dialogs(self) -> List[DialogMessage]:
        """Получает все диалоги пользователя (с использованием конкурентной загрузки страниц)."""
        # Примечание: endpoint 'dialogs' на Kwork, похоже, не содержит информации о пагинации.
        # Будет выполняться последовательная загрузка, пока не вернётся пустая страница.
        page = 1
        dialogs = []
        token = await self.token
        while True:
            dialogs_page = await self.request(method="post", api_method="dialogs", filter="all", page=page, token=token)
            if not dialogs_page["response"]:
                break
            dialogs.extend(DialogMessage(**dialog) for dialog in dialogs_page["response"])
            page += 1
        return dialogs

    async def get_dialog_with_user(self, user_name: str) -> List[InboxMessage]:
        """Получает диалог с конкретным пользователем (с использованием конкурентной загрузки страниц)."""
        return await self._fetch_paginated_data(
            model=InboxMessage,
            api_method="inboxes",
            username=user_name,
            token=await self.token
        )

    async def get_projects(self, categories_ids: List[Union[int, str]], price_from: Optional[int] = None, price_to: Optional[int] = None, hiring_from: Optional[int] = None,
                           kworks_filter_from: Optional[int] = None, kworks_filter_to: Optional[int] = None, page: Optional[int] = None, query: Optional[str] = None) -> List[WantWorker]:
        """
        Поиск проектов по критериям.
        Если `page` указан, будет возвращена только эта страница.
        Если `page` не указан, асинхронно загрузятся и вернутся ВСЕ страницы.
        """
        if not categories_ids:
            raise KworkValidationException("categories_ids cannot be empty")

        common_params = {
            "categories": ",".join(str(c) for c in categories_ids),
            "price_from": price_from,
            "price_to": price_to,
            "hiring_from": hiring_from,
            "kworks_filter_from": kworks_filter_from,
            "kworks_filter_to": kworks_filter_to,
            "query": query,
            "token": await self.token
        }

        
        if page is not None:
            raw_projects = await self.request(
                method="post",
                api_method="projects",
                page=page,
                **common_params
            )
            return [WantWorker(**dict_project) for dict_project in raw_projects.get("response", [])]
        
    # --- Улучшение: если page не указан, загружаем все страницы параллельно ---
        else:
            return await self._fetch_paginated_data(
                model=WantWorker,
                api_method="projects",
                **common_params
            )

    # --- Методы ниже не изменялись, так как не используют пагинацию или уже реализованы корректно ---

    async def get_me(self) -> Actor:
        """Получает информацию о текущем пользователе"""
        actor = await self.request(method="post", api_method="actor", token=await self.token)
        return Actor(**actor["response"])

    async def get_user(self, user_id: int) -> User:
        """Получает информацию о пользователе"""
        user = await self.request(method="post", api_method="user", id=user_id, token=await self.token)
        return User(**user["response"])

    async def set_offline(self) -> Dict:
        """Устанавливает статус офлайн"""
        return await self.request(method="post", api_method="offline", token=await self.token)
    
    async def set_online(self) -> Dict:
        """Устанавливает статус онлайн"""
        return await self.request(method="post", full_url="https://kwork.ru/user_online", token=await self.token)
    
    async def set_typing(self, recipient_id: int) -> Dict:
        """Устанавливает статус "печатает" в диалоге"""
        return await self.request(method="post", api_method="typing", recipientId=recipient_id, token=await self.token)

    async def get_worker_orders(self) -> Dict:
        """Получает заказы исполнителя"""
        return await self.request(method="post", api_method="workerOrders", filter="all", token=await self.token)

    async def get_payer_orders(self) -> Dict:
        """Получает заказы заказчика"""
        return await self.request(method="post", api_method="payerOrders", filter="all", token=await self.token)

    async def get_notifications(self) -> Dict:
        """Получает уведомления"""
        return await self.request(method="post", api_method="notifications", token=await self.token)

    async def get_categories(self) -> List[Category]:
        """Получает категории проектов"""
        categories = await self.request(method="post", api_method="categories", type="1", token=await self.token)
        return [Category(**dict_category) for dict_category in categories["response"]]

    async def get_connects(self) -> Connects:
        """Получает информацию об откликах"""
        projects = await self.request(method="post", api_method="projects", categories="", token=await self.token)
        return Connects(**projects["connects"])

    async def _get_channel(self) -> str:
        """Получает канал подключения"""
        channel = await self.request(method="post", api_method="getChannel", token=await self.token)
        return channel["response"]["channel"]

    async def send_message(self, user_id: int, text: str) -> Dict:
        """Отправляет сообщение пользователю"""
        if not text or not user_id:
            raise KworkValidationException("user_id и text не могут быть пустыми")
        logger.debug(f"Отправка сообщения пользователю {user_id}")
        return await self.request(method="post", api_method="inboxCreate", user_id=user_id, text=text, token=await self.token)

    async def delete_message(self, message_id: int) -> Dict:
        """Удаляет сообщение"""
        return await self.request(method="post", api_method="inboxDelete", id=message_id, token=await self.token)