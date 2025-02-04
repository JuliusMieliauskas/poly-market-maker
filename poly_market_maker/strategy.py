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
from poly_market_maker.utils import count_decimal_places


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

    def calculate_depth_weighted_spread(self, bids, asks, depth = 5, round_decimals = 5):
        # Market spread adjusted for 'depth' levels of order book
        # Calculated by the fomula:
        # weighted_spread = SUM((ask_price_i - bid_price_i) * min(ask_size_i, bid_size_i)) / SUM(min(ask_size_i, bid_size_i))
        # where i is the ith level of the order book (i = 0, 1, 2, ..., depth-1)
        if bids is None or asks is None:
            return float("inf")
        if len(bids) < depth or len(asks) < depth:
            return float("inf")
            
        total_volume_user_for_weighting = 0
        total_spread = 0
        for i in range(depth):
            total_volume_user_for_weighting += min(bids[i]['size'], asks[i]['size'])
            total_spread += (asks[i]['price'] - bids[i]['price']) * min(bids[i]['size'], asks[i]['size'])

        if total_volume_user_for_weighting == 0:
            return float("inf")
        return round(total_spread / total_volume_user_for_weighting, round_decimals)
    
    def get_spread_where_order_value_exceeds_max_collateral(self, orders, midpoint, max_collateral, round_decimals = 5):
        # Calculate the spread where the value of the sum of bid/ask exceeds max collateral
        total_sum_of_bids = 0
        for i in range(len(orders)):
            total_sum_of_bids += orders[i]['price']*orders[i]['size']
            if total_sum_of_bids > max_collateral:
                if i == 0 and total_sum_of_bids < 2*max_collateral:
                    # If the first order is already over the max collateral, only return the spread of the first order if 
                    # the size of it is more than 2*max_collateral, else return the spread of the second order
                    i = i + 1
                return abs(round(midpoint - orders[i]['price'], round_decimals))
        return float("inf")
    
    def synchronize(self):
        try:
            orderbook = self.get_order_book()
        except Exception as e:
            self.logger.error(f"{e}")
            return

        market_spread = float("inf")
        my_order_spread_token_A = float("inf")
        my_order_spread_token_B = float("inf")
        midpoint = 0
        token_prices = {Token.A: 0.0, Token.B: 0.0}
        token_market_order_book = self.get_token_order_book()

        if token_market_order_book is not None:
            bids = token_market_order_book['bids']
            asks = token_market_order_book['asks']
            self.logger.debug(f"Token market order book bids: {bids}")
            self.logger.debug(f"Token market order book asks: {asks}")

            if bids is not None and asks is not None and bids.__len__() > 0 and asks.__len__() > 0:
                midpoint = (bids[0]['price'] + asks[0]['price']) / 2
                my_order_spread_token_A = self.get_spread_where_order_value_exceeds_max_collateral(bids, midpoint, max_collateral=self.strategy.amm_manager.max_collateral)
                self.logger.debug(f"Bid spread to exceed the collateral: {my_order_spread_token_A}")
                my_order_spread_token_B = self.get_spread_where_order_value_exceeds_max_collateral(asks, midpoint, max_collateral=self.strategy.amm_manager.max_collateral)
                self.logger.debug(f"Ask spread to exceed the collateral: {my_order_spread_token_B}")
                token_prices = {Token.A: midpoint, Token.B: 1 - midpoint}
                market_spread = round(asks[0]['price'] - bids[0]['price'], MAX_DECIMALS)
                self.logger.debug(f"Midpoint: {midpoint}")
                self.logger.debug(f"Market spread: {market_spread}")

        self.logger.debug(f"My order spread for token A: {my_order_spread_token_A}")
        self.logger.debug(f"My order spread for token B: {my_order_spread_token_B}")
        
        (orders_to_cancel, orders_to_place) = self.strategy.get_orders(
            orderbook, token_prices, my_order_spread_token_A, my_order_spread_token_B
        )

        self.logger.debug(f"order to cancel: {len(orders_to_cancel)}")
        self.logger.debug(f"order to place: {len(orders_to_place)}")

        self.cancel_orders(orders_to_cancel)
        self.place_orders(orders_to_place)

        self.logger.debug("Synchronized strategy! In total placed {} orders".format(len(orders_to_place)))
        return len(orders_to_place)

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
