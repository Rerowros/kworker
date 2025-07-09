import json
import logging
import collections
import aiohttp
from typing import Optional, Union, List, Dict
from aiohttp_socks import ProxyConnector
from models import Actor, User, DialogMessage, InboxMessage, Category, Connects, WantWorker
from exceptions import *

logger = logging.getLogger(__name__)
Handler = collections.namedtuple("Handler", ["func", "text", "on_start", "text_contains"])

class KworkAPI:
    """Клиент для работы с API Kwork.ru
    Args:
        login: Логин аккаунта Kwork
        password: Пароль аккаунта
        proxy: Прокси в формате `socks5://user:pass@host:port`
        phone_last: Последние 4 цифры телефона
    """
    def __init__(self, login: str, password: str, proxy: Optional[str] = None, phone_last: Optional[str] = None):
        self.session = aiohttp.ClientSession(connector=self._create_connector(proxy))
        self.host = "https://api.kwork.ru/{}"
        self.login = login
        self.password = password
        self._token: Optional[str] = None
        self.phone_last = phone_last
        
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def _create_connector(self, proxy: Optional[str]) -> Optional[aiohttp.BaseConnector]:
        """Создает коннектор для прокси"""
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

    async def request(self, method: str, api_method: Optional[str] = None, full_url: Optional[str] = None, timeout: int = 10, **params) -> Union[Dict, List]:
        """Выполняет API запрос с обработкой ошибок
        Args:
            method (str): HTTP метод
            api_method (Optional[str]): Название метода API
            full_url (Optional[str]): Полный URL запроса
            params: Параметры запроса
        Returns:
            JSON ответ запроса
        """
        params = {k: v for k, v in params.items() if v is not None}
        logger.debug(f"Request: {method} {api_method} with params: {params}")

        if not (api_method or full_url):
            raise KworkApiException("Необходимо указать api_method или full_url")

        url = full_url or self.host.format(api_method)
        request_info = {"method": method, "url": url, "params": params}

        try:
            async with self.session.request(method=method, url=url, headers={"Authorization": "Basic bW9iaWxlX2FwaTpxRnZmUmw3dw=="}, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:

                if resp.content_type != "application/json":
                    error_text = await resp.text()
                    raise KworkApiException(f"Недопустимый формат ответа: {error_text}", request_info=request_info)

                json_response = await resp.json()
                logger.debug(f"Response: {json_response}")

                if not json_response.get("success"):
                    error_msg = json_response.get("error", "Unknown error")
                    error_code = json_response.get("error_code")

                    exc_params = {"code": error_code, "request_info": request_info}

                    if "limit" in error_msg.lower():
                        raise KworkRateLimitException(error_msg, **exc_params)
                    elif "auth" in error_msg.lower() or "token" in error_msg.lower():
                        raise KworkAuthException(error_msg, **exc_params)
                    else:
                        raise KworkApiException(error_msg, **exc_params)
                return json_response
        except aiohttp.ClientError as e:
            raise KworkConnectionException(f"Ошибка сети: {str(e)}", request_info=request_info)
        except json.JSONDecodeError as e:
            raise KworkApiException(f"Недопустимый json: {str(e)}", request_info=request_info)
        except Exception as e:
            raise KworkException(f"Неизвестная ошибка: {str(e)}", request_info=request_info)

    async def close(self) -> None:
        """Закрывает HTTP сессию"""
        await self.session.close()

    async def get_token(self) -> str:
        """Получает токен авторизации
        Returns:
            Авторизационный токен
        """
        resp = await self.request(method="post", api_method="signIn", login=self.login, password=self.password, phone_last=self.phone_last)
        return resp["response"]["token"]

    async def get_me(self) -> Actor:
        """Получает информацию о текущем пользователе
        Returns:
            Объект Actor с данными пользователя
        """
        actor = await self.request(method="post", api_method="actor", token=await self.token)
        return Actor(**actor["response"])

    async def get_user(self, user_id: int) -> User:
        """Получает информацию о пользователе
        Args:
            user_id: ID пользователя
        Returns:
            Объект User с данными пользователя
        """
        user = await self.request(method="post", api_method="user", id=user_id, token=await self.token)
        return User(**user["response"])

    async def get_all_dialogs(self) -> List[DialogMessage]:
        """Получает все диалоги пользователя
        Returns:
            Список объектов DialogMessage
        """
        page = 1
        dialogs = []

        while True:
            dialogs_page = await self.request(method="post", api_method="dialogs", filter="all", page=page, token=await self.token)
            if not dialogs_page["response"]:
                break

            dialogs.extend(DialogMessage(**dialog) for dialog in dialogs_page["response"])
            page += 1
        return dialogs

    async def set_offline(self) -> Dict:
        """Устанавливает статус офлайн"""
        return await self.request(method="post", api_method="offline", token=await self.token)
    
    async def set_online(self) -> Dict:
        """Устанавливает статус онлайн"""
        return await self.request(method="post", full_url="https://kwork.ru/user_online", token=await self.token)
    
    async def set_typing(self, recipient_id: int) -> Dict:
        """Устанавливает статус "печатает" в диалоге
        Args:
            recipient_id: ID получателя
        """
        return await self.request(method="post", api_method="typing", recipientId=recipient_id, token=await self.token)

    async def get_dialog_with_user(self, user_name: str) -> List[InboxMessage]:
        """Получает диалог с конкретным пользователем
        Args:
            user_name: Имя пользователя
        Returns:
            Список сообщений InboxMessage
        """
        page = 1
        dialog = []

        while True:
            messages_dict = await self.request(method="post", api_method="inboxes", username=user_name, page=page, token=await self.token)
            if not messages_dict.get("response"):
                break

            dialog.extend(InboxMessage(**message) for message in messages_dict["response"])

            if page == messages_dict["paging"]["pages"]:
                break
            page += 1
        return dialog

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

    async def get_projects(self, categories_ids: List[Union[int, str]], price_from: Optional[int] = None, price_to: Optional[int] = None, hiring_from: Optional[int] = None,
                           kworks_filter_from: Optional[int] = None, kworks_filter_to: Optional[int] = None, page: Optional[int] = None, query: Optional[str] = None) -> List[WantWorker]:
        """Поиск проектов по критериям
        Args:
            categories_ids: Список ID категорий
            price_from: Минимальная цена
            price_to: Максимальная цена
            hiring_from: Минимальный процент найма
            kworks_filter_from: Минимальное количество работ
            kworks_filter_to: Максимальное количество работ
            page: Номер страницы
            query: Поисковый запрос
        Returns:
            Список проектов WantWorker
        """
        if not categories_ids:
            raise KworkValidationException("categories_ids cannot be empty")

        raw_projects = await self.request(
            method="post",
            api_method="projects",
            categories=",".join(str(c) for c in categories_ids),
            price_from=price_from,
            price_to=price_to,
            hiring_from=hiring_from,
            kworks_filter_from=kworks_filter_from,
            kworks_filter_to=kworks_filter_to,
            page=page,
            query=query,
            token=await self.token
        )
        return [WantWorker(**dict_project) for dict_project in raw_projects["response"]]

    async def _get_channel(self) -> str:
        """Получает канал подключения"""
        channel = await self.request(method="post", api_method="getChannel", token=await self.token)
        return channel["response"]["channel"]

    async def send_message(self, user_id: int, text: str) -> Dict:
        """Отправляет сообщение пользователю
        Args:
            user_id: ID получателя
            text: Текст сообщения
        """
        if not text or not user_id:
            raise KworkValidationException("user_id and text cannot be empty")

        logger.debug(f"Sending message to {user_id}")
        return await self.request(method="post", api_method="inboxCreate", user_id=user_id, text=text, token=await self.token)

    async def delete_message(self, message_id: int) -> Dict:
        """Удаляет сообщение
        Args:
            message_id: ID сообщения
        """
        return await self.request(method="post", api_method="inboxDelete", id=message_id, token=await self.token)
