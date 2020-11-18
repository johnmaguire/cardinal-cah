from mock import Mock

from cardinal.bot import (
    CardinalBot,
    user_info,
)

from . import game
from .plugin import CAHPlugin


class TestPlugin(object):
    def setup_method(self):
        self.channel = '#cah'
        self.player = 'player1'
        self.user = user_info(self.player, 'user', 'vhost')

        self.mock_cardinal = Mock(spec=CardinalBot)
        self.mock_cardinal.nickname = 'Cardinal'

        self.plugin = CAHPlugin(self.mock_cardinal,
                                {'channel': self.channel})

        self.plugin.game = game.Game()
        self.plugin.game.add_player(self.player)

    def test_play_wrong_channel(self):
        channel = '#invalid-channel'
        self.plugin.ready(self.mock_cardinal,
                          self.user,
                          channel,
                          '.play')

        self.mock_cardinal.sendMsg.assert_called_once_with(
            channel,
            "Please start the game in {}!".format(self.channel))

    def test_choose_waiting_in_pm(self):
        # when command sent in pm, respond in pm
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.player,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.player,
            "Please wait for your turn.",
        )

    def test_choose_waiting_in_channel(self):
        # went command sent in channel, respond in channel
        self.plugin.choose(self.mock_cardinal,
                           self.user,
                           self.channel,
                           ".choose 1")

        self.mock_cardinal.sendMsg.assert_called_once_with(
            self.channel,
            "Please wait for your turn.",
        )
