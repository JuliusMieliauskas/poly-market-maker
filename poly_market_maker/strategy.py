from enum import Enum
import json
import logging

from poly_market_maker.orderbook import OrderBookManager
from poly_market_maker.price_feed import PriceFeed
from poly_market_maker.token import Token, Collateral
from poly_market_maker.constants import MAX_DECIMALS

from poly_market_maker.strategies.base_strategy import BaseStrategy
from poly_market_maker.strategies.amm_strategy import AMMStrategy
from poly_market_maker.strategies.bands_strategy import BandsStrategy


class Strategy(Enum):
    AMM = "amm"
    BANDS = "bands"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            for strategy in Strategy:
                if value.lower() == strategy.value.lower():
                    return strategy
        return super()._missing_(value)


class StrategyManager:
    def __init__(
        self,
        strategy: str,
        config_path: str,
        price_feed: PriceFeed,
        order_book_manager: OrderBookManager,
    ) -> BaseStrategy:
        self.logger = logging.getLogger(self.__class__.__name__)

        with open(config_path) as fh:
            config = json.load(fh)

        self.price_feed = price_feed
        self.order_book_manager = order_book_manager

        match Strategy(strategy):
            case Strategy.AMM:
                self.strategy = AMMStrategy(config)
            case Strategy.BANDS:
                self.strategy = BandsStrategy(config)
            case _:
                raise Exception("Invalid strategy")

    def synchronize(self):
        self.logger.debug("Synchronizing strategy...")

        try:
            orderbook = self.get_order_book()
        except Exception as e:
            self.logger.error(f"{e}")
            return

        token_prices = self.get_token_prices()
        self.logger.debug(f"Token prices: {token_prices}")
        
        market_spread = self.get_token_spread()
        my_order_spread = market_spread

        token_market_order_book = self.get_token_order_book()
        if token_market_order_book is not None:
            # self.logger.debug(f"Token market order book: {token_market_order_book}")
            self.logger.debug(f"Token market order book: {token_market_order_book.__len__()}")
            midpoint = token_prices[Token.A]
            bids = token_market_order_book['bids']
            self.logger.debug(f"Midpoint: {midpoint}\nToken market order book bids: {bids}")
            if bids is not None and bids.__len__() >= 3:
                my_order_spread = (midpoint - bids[1]['price']) + round(bids[1]['price'] - bids[2]['price'], MAX_DECIMALS)

        self.logger.debug(f"New market spread: {market_spread}")
        self.logger.debug(f"My order spread: {my_order_spread}")
        
        (orders_to_cancel, orders_to_place) = self.strategy.get_orders(
            orderbook, token_prices, my_order_spread
        )

        self.logger.debug(f"order to cancel: {len(orders_to_cancel)}")
        self.logger.debug(f"order to place: {len(orders_to_place)}")

        self.cancel_orders(orders_to_cancel)
        self.place_orders(orders_to_place)

        self.logger.debug("Synchronized strategy!")

    def get_order_book(self):
        orderbook = self.order_book_manager.get_order_book()

        if None in orderbook.balances.values():
            self.logger.debug("Balances invalid/non-existent")
            raise Exception("Balances invalid/non-existent")

        if sum(orderbook.balances.values()) == 0:
            self.logger.debug("Wallet has no balances for this market")
            raise Exception("Zero Balances")

        return orderbook

    def get_token_prices(self):
        price_a = round(
            self.price_feed.get_price(Token.A),
            MAX_DECIMALS,
        )
        price_b = round(1 - price_a, MAX_DECIMALS)
        return {Token.A: price_a, Token.B: price_b}
    
    def get_token_spread(self):
        spread = round(
            self.price_feed.get_spread(Token.A),
            MAX_DECIMALS,
        )
        return spread
    
    def get_token_order_book(self):
        token_book = self.price_feed.get_order_book(Token.A)
        return token_book

    def cancel_orders(self, orders_to_cancel):
        if len(orders_to_cancel) > 0:
            self.logger.info(
                f"About to cancel {len(orders_to_cancel)} existing orders!"
            )
            self.order_book_manager.cancel_orders(orders_to_cancel)

    def place_orders(self, orders_to_place):
        if len(orders_to_place) > 0:
            self.logger.info(f"About to place {len(orders_to_place)} new orders!")
            self.order_book_manager.place_orders(orders_to_place)
