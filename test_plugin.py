from mock import Mock

from cardinal.bot import (
    CardinalBot,
    user_info,
)

from game import Game
from plugin import CAHPlugin


class TestPlugin(object):
    def setup_method(self):
        self.channel = '#channel'
        self.player = 'player1'
        self.user = user_info(self.player, 'user', 'vhost')

        self.mock_cardinal = Mock(spec=CardinalBot)
        self.mock_cardinal.nickname = 'Cardinal'

        self.plugin = CAHPlugin(self.mock_cardinal,
                                [self.channel])

        self.plugin.games[self.channel] = Game()
        self.plugin.games[self.channel].add_player(self.player)

    def test_choose_waiting_in_pm(self):
        # when command sent in pm, respond in pm
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.player,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.player,
            "Wait for your turn please.",
        )

    def test_choose_waiting_in_channel(self):
        # went command sent in channel, respond in channel
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.channel,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.channel,
            "Wait for your turn please.",
        )
