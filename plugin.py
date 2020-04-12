import logging
from cardinal.decorators import command, event, help

from game import (Game, Player,
                  InvalidMoveError, InvalidPickError, InvalidChoiceError,
                  PlayerExistsError, NotEnoughPlayersError)


class CAHPlugin(object):
    def __init__(self, cardinal, config):
        self.logger = logging.getLogger(__name__)
        self.cardinal = cardinal

        self.games = {}
        self.channels = []

        if 'channels' not in config:
            return

        self.channels = [str(channel) for channel in config['channels']]

    @command('play')
    @help("Joins or starts a new Cardinals Against Humanity game")
    @help("Syntax: .play")
    def play(self, cardinal, user, channel, msg):
        nick = user.nick

        # Check if CAH is allowed here
        if channel not in self.channels:
            return cardinal.sendMsg(nick,
                                    "Sorry, CAH isn't allowed here. Try "
                                    "one of these channels instead: {}"
                                    .format(' '.join(self.channels)))

        # Attempt to get the game
        try:
            game = self.games[channel]
        # Create a new game and add the player to it
        except KeyError:
            self.games[channel] = Game()
            self.games[channel].add_player(nick)

            cardinal.sendMsg(
                channel, "A new game of Cardinals Against Humanity has been "
                         "created. You've automatically been joined. Other "
                         "players can use .play to join.")
            cardinal.sendMsg(
                channel, "You can use .ready to start the game. Have fun!")
            return

        try:
            game.add_player(nick)
        except InvalidMoveError:
            cardinal.sendMsg(channel, "The game is already in progress.")
            return
        except PlayerExistsError:
            cardinal.sendMsg(channel, "You're already playing :)")
            return

        cardinal.sendMsg(channel, "{} has joined the game.".format(nick))
        cardinal.sendMsg(channel, "Players: {}".format(', '.join([
            player for player in game.players
        ])))

    @command(['ready', 'start'])
    @help("Begin the CAH game!")
    @help('Syntax: .ready/.start')
    def ready(self, cardinal, user, channel, msg):
        try:
            game = self.games[channel]
            game.ready()
        except InvalidMoveError:
            cardinal.sendMsg(channel, "The game has already begun.")
            return
        except KeyError:
            cardinal.sendMsg(channel, "No game in progress. "
                                      "Type .cah to start one!")
        except NotEnoughPlayersError:
            cardinal.sendMsg(channel, "Not enough players to begin the game!")
            return

        cardinal.sendMsg(channel, "The game has begun! We will be playing "
                                  "until someone earns {} points.".format(
                                      game.max_points))

        self.show_black_card(channel)
        self.show_hands(channel)

    @command(['choose', 'c'])
    @help("Choose cards to play")
    @help("Syntax: .choose <choice [choice, [..]]>")
    def choose(self, cardinal, user, channel, msg):
        """Play a card or card combination"""
        nick = user.nick

        # Get the choices
        choices = msg.strip().split(' ')[1:]

        # If only one game is running, let them use PM
        game_channel = channel
        if nick == channel and len(self.games) == 1:
            game_channel = self.games.keys()[0]
        elif nick == channel:
            cardinal.sendMsg(channel, "Use .choose in the game channel!")
            return

        try:
            game = self.games[game_channel]
        # Ignore invalid channel
        except KeyError:
            return

        try:
            player = game.players[nick]
        # Ignore invalid player
        except KeyError:
            return

        if (game.state == Game.STARTING or \
                player.state == Player.WAITING):
            cardinal.sendMsg(channel, "Wait for your turn please.")
            return

        if player.state == Player.CHOOSING:
            # Make player choice
            try:
                player.choose(choices)
            except InvalidChoiceError as e:
                cardinal.sendMsg(channel, e.message)
                return
            except InvalidMoveError:
                pass

            # Check if game transitioned
            if game.state == Game.WAITING_PICK:
                self.show_choices(game_channel)
            else:
                choosing = []
                for _, p in game.players.items():
                    if p.state == Player.CHOOSING:
                        choosing.append(p.name)

                cardinal.sendMsg(game_channel,
                                 "{} has chosen. Still choosing: {}"
                                 .format(player.name, ', '.join(choosing)))

        elif player.state == Player.PICKING:
            # Make sure they aren't flubbing the command
            if len(choices) > 1:
                cardinal.sendMsg(
                    channel,
                    "You may only pick one winner."
                )
                return

            # Make player pick
            try:
                win = game.pick(choices[0])
                winner = win[0]
                card = win[1]
            except InvalidPickError:
                cardinal.sendMsg(channel, "Invalid pick. Please try again!")
                return
            except InvalidMoveError:
                pass

            cardinal.sendMsg(game_channel,
                             "{} won the round with '{}' Congrats! You "
                             "have {} point(s).".format(winner.name,
                                                        card,
                                                        winner.points))

            # Check if game transitioned, and show new choices
            if game.state == Game.WAITING_CHOICES:
                self.show_black_card(game_channel)
                self.show_hands(game_channel)

        if game.state == Game.OVER:
            self.finish_game(game_channel)

    @command('score')
    @help("Give Cards Against Humanity score")
    @help("Syntax: .score")
    def score(self, cardinal, channel, msg):
        self.send_scores(channel)

    @event('irc.kick')
    def _kicked(self, cardinal, kicker, channel, kicked, _):
        """Remove kicked players from the game"""
        try:
            self.remove_player(channel, kicked)
        except KeyError:
            return

    @event('irc.part')
    def _left(self, cardinal, leaver, channel, _):
        """Remove players who part from the game"""
        try:
            self.remove_player(channel, leaver.nick)
        except KeyError:
            return

    @event('irc.quit')
    def _quit(self, cardinal, quitter, _):
        """Remove players who quit from the game"""
        for channel, _ in self.games.items():
            try:
                self.remove_player(channel, quitter.nick)
            except KeyError:
                return

    def remove_player(self, channel, player):
        """Removes a player from a channel's game.

        Raises:
          KeyError -- If a game or player doesn't exist.
        """
        game = self.games[channel]

        initial_state = game.state

        self.games[channel].remove_player(player)
        self.cardinal.sendMsg(channel, "{} left the game!".format(player))

        if (initial_state == Game.WAITING_PICK and
                game.state == Game.WAITING_CHOICES):
            self.cardinal.sendMsg(channel, "Round skipped.")
            self.show_black_card(channel)
            self.show_hands(channel)

        elif (initial_state == Game.WAITING_CHOICES and
              game.state == Game.WAITING_PICK):
            self.show_choices(channel)

        elif game.state == Game.OVER:
            self.cardinal.sendMsg(channel, "The game has ended by default.")
            self.finish_game(channel)

    def show_hands(self, channel):
        game = self.games[channel]

        for nick, player in game.players.items():
            if player.state == Player.WAITING:
                self.cardinal.sendMsg(nick, "You are picking this round.")
                continue

            hand = []

            # Instructions
            syntax = ['<choice>' for _ in xrange(game.required_cards)]
            syntax.insert(0, '.choose')
            self.cardinal.sendMsg(nick,
                                  "Use {} to make your choice(s)."
                                  .format(' '.join(syntax)))

            # Hand
            for idx, card in enumerate(player.hand):
                hand.append("[{}] {}".format(idx, card))
            self.cardinal.sendMsg(nick, "Hand: {}".format(' '.join(hand)))

            # Prompt (black card)
            self.cardinal.sendMsg(nick,
                                  "Black card: {} | Player picking: {}"
                                  .format(
                                        game.black_card.replace('%s', '____'),
                                        game.picker.name,
                                  ))

    def show_black_card(self, channel):
        game = self.games[channel]

        self.cardinal.sendMsg(channel,
                              "Black card: {} | Player picking: {}"
                              .format(
                                    game.black_card.replace('%s', '____'),
                                    game.picker.name,
                              ))

    def show_choices(self, channel):
        game = self.games[channel]

        # No blanks, show prompt
        if '%s' not in game.black_card:
            self.cardinal.sendMsg(channel, "{}".format(game.black_card))

        for idx, choice in enumerate(game.choices):
            # Send the option
            self.cardinal.sendMsg(channel, "[{}] {}".format(idx, choice[1]))

        self.cardinal.sendMsg(channel,
                              "{}: Make your choice with .choose!"
                              .format(game.picker.name))

    def send_scores(self, channel):
        game = self.games[channel]

        standing = 0
        for name, player in game.scores:
            standing += 1
            self.cardinal.sendMsg(channel,
                                  "{}. {} - {} points"
                                  .format(standing, name, player.points))

    def finish_game(self, channel):
        try:
            game = self.games[channel]

            self.send_scores(channel)

            # Close the game cleanly
            game.close()
        finally:
            del self.games[channel]

            self.cardinal.sendMsg(channel, "Good game! You may use .play to start "
                                           "a new one.")

    def close(self, cardinal):
        # TODO: Kill off running timers

        for channel in self.games:
            self.games[channel].close()
        self.games.clear()


def setup(cardinal, config):
    return CAHPlugin(cardinal, config)
