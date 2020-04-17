import logging
import os

import game

from cardinal.decorators import command, event, help

# make sure game module is reloaded when the plugin is reloaded - don't do this
# during test execution or assertions will fail
if "PYTEST" not in os.environ:
    reload(game)


class CAHPlugin(object):
    def __init__(self, cardinal, config):
        self.logger = logging.getLogger(__name__)
        self.cardinal = cardinal

        self.channel = config['channel']

        self.game = None

    @command('play')
    @help("Joins or starts a new Cardinals Against Humanity game")
    @help("Syntax: .play [max points]")
    def play(self, cardinal, user, channel, msg):
        # Check if CAH is allowed here
        if channel != self.channel:
            return cardinal.sendMsg(channel,
                                    "Sorry, CAH isn't allowed here. Please "
                                    "join {} to start a game."
                                    .format(self.channel))

        # Attempt to get the game
        if not self.game:
            msg_parts = msg.split(' ')
            try:
                max_points = int(msg_parts[1])
            except Exception:
                max_points = 5

            if max_points < 5 or max_points > 10:
                cardinal.sendMsg(channel, "Game can be played up to a minimum "
                                          "of 5 points and a maximum of 10 "
                                          "points.")
                return

            self.game = game.Game(max_points)
            self.game.add_player(user.nick)

            cardinal.sendMsg(
                channel, "A new game of Cardinal Against Humanity has been "
                         "created. You've been joined automatically. Other "
                         "players can use .play to join.")
            cardinal.sendMsg(
                channel, "Each round, a prompt will be given. All players "
                         "except for the judge of that round will choose a "
                         "card or multiple cards to play from their hand, "
                         "depending on the prompt.")
            cardinal.sendMsg(
                channel, "Once all players have made their choices, the judge "
                         "will pick their favorite. The game will end once a "
                         "player reaches {} points or there are no cards "
                         "left.".format(self.game.max_points))
            cardinal.sendMsg(
                channel, "When you're ready to start the game, just say "
                         ".ready and we'll begin. Have fun and good luck!")
            return

        try:
            self.game.add_player(user.nick)
        except game.InvalidMoveError:
            cardinal.sendMsg(channel, "The game is already in progress.")
            return
        except game.PlayerExistsError:
            cardinal.sendMsg(channel, "You're already playing :)")
            return

        cardinal.sendMsg(channel, "{} has joined the game.".format(user.nick))
        cardinal.sendMsg(channel, "Players: {}".format(', '.join([
            player for player in self.game.players
        ])))

    @command(['ready', 'start'])
    @help("Begin the CAH game!")
    @help('Syntax: .ready/.start')
    def ready(self, cardinal, user, channel, msg):
        if channel != self.channel:
            cardinal.sendMsg(channel, "Please start the game in {}!"
                                      .format(self.channel))
            return

        if not self.game:
            cardinal.sendMsg(channel, "No game in progress. Start one with "
                                      ".play!")
            return

        try:
            self.game.ready()
        except game.InvalidMoveError:
            cardinal.sendMsg(channel, "The game has already begun.")
            return
        except game.NotEnoughPlayersError:
            cardinal.sendMsg(channel, "Not enough players to begin the game!")
            return

        cardinal.sendMsg(channel, "The game has begun! We will be playing "
                                  "until someone earns {} points or we run "
                                  "out of cards."
                                  .format(self.game.max_points))

        self.show_black_card()
        self.show_hands()

    @command(['choose', 'c'])
    @help("Choose cards to play")
    @help("Syntax: .choose <choice [choice, [..]]>")
    def choose(self, cardinal, user, channel, msg):
        """Play a card or card combination"""
        nick = user.nick

        # Get the choices
        choices = msg.strip().split(' ')[1:]

        if not self.game:
            if channel == self.channel:
                message = "No game in progress. Start one with .play!"
            else:
                message = "No game in progress. Start one in {}.".format(
                    self.channel)

            cardinal.sendMsg(channel, message)
            return

        try:
            player = self.game.players[nick]
        # Ignore invalid player
        except KeyError:
            cardinal.sendMsg(channel, "It doesn't look like you're playing. "
                                      "Join in next time!")

        if (self.game.state == game.Game.STARTING or
                player.state == game.Player.WAITING):
            cardinal.sendMsg(channel, "Please wait for your turn.")
            return

        if player.state == game.Player.CHOOSING:
            # Make player choice
            try:
                player.choose(choices)
            except game.InvalidChoiceError as e:
                cardinal.sendMsg(channel, e.message)
                return
            except game.InvalidMoveError:
                pass

            # Check if game transitioned
            if self.game.state == game.Game.WAITING_PICK:
                self.show_choices()
            else:
                choosing = []
                for _, p in self.game.players.items():
                    if p.state == game.Player.CHOOSING:
                        choosing.append(p.name)

                cardinal.sendMsg(self.channel,
                                 "{} has chosen. Still choosing: {}"
                                 .format(player.name, ', '.join(choosing)))

        elif player.state == game.Player.PICKING:
            # Make sure they aren't flubbing the command
            if len(choices) > 1:
                cardinal.sendMsg(
                    channel,
                    "You may only pick one winner."
                )
                return

            # Make player pick
            try:
                player, card = self.game.pick(choices[0])
            except game.InvalidPickError:
                cardinal.sendMsg(channel, "Invalid pick. Please try again!")
                return
            except game.InvalidMoveError:
                pass

            cardinal.sendMsg(self.channel,
                             "{} won the round with '{}' Congrats! You "
                             "have {} point(s).".format(player.name,
                                                        card,
                                                        player.points))

            # Check if game transitioned, and show new choices
            if self.game.state == game.Game.WAITING_CHOICES:
                self.show_black_card()
                self.show_hands()

        if self.game.state == game.Game.OVER:
            self.finish_game()

    @command('score')
    @help("Give Cards Against Humanity score")
    @help("Syntax: .score")
    def score(self, cardinal, user, channel, msg):
        if channel != self.channel:
            cardinal.sendMsg(channel, "Please check the score in {}!"
                                      .format(self.channel))
            return

        if not self.game:
            cardinal.sendMsg(channel, "No game in progress. Start one with "
                                      ".play!")
            return

        self.send_scores()

    @event('irc.kick')
    def _kicked(self, cardinal, kicker, channel, kicked, _):
        """Remove kicked players from the game"""
        if channel != self.channel:
            return

        try:
            self.remove_player(kicked)
        except KeyError:
            return

    @event('irc.part')
    def _left(self, cardinal, leaver, channel, _):
        """Remove players who part from the game"""
        if channel != self.channel:
            return

        try:
            self.remove_player(leaver.nick)
        except KeyError:
            return

    @event('irc.quit')
    def _quit(self, cardinal, quitter, _):
        """Remove players who quit from the game"""
        try:
            self.remove_player(quitter.nick)
        except KeyError:
            return

    def remove_player(self, player):
        """Removes a player from a channel's game.

        Raises:
          KeyError -- If a game or player doesn't exist.
        """
        if not self.game:
            return

        initial_state = self.game.state

        self.game.remove_player(player)
        self.cardinal.sendMsg(self.channel, "{} left the game!".format(player))

        # if game went from waiting pick to waiting choices, then this player
        # was the card czar.
        if (initial_state == game.Game.WAITING_PICK and
                self.game.state == game.Game.WAITING_CHOICES):
            self.cardinal.sendMsg(self.channel,
                                  "Round skipped since {} was supposed to "
                                  "pick a winner.".format(player))

            self.show_black_card()
            self.show_hands()

        # if this was the last player we were waiting on for a choice, then
        # move on to having the card czar pick
        elif (initial_state == game.Game.WAITING_CHOICES and
                self.game.state == game.Game.WAITING_PICK):
            self.show_choices()

        # otherwise, if we ran out of players, end the game...
        elif self.game.state == game.Game.OVER:
            self.cardinal.sendMsg(self.channel,
                                  "The game has ended due to lack of players.")
            self.finish_game()

    def show_hands(self):
        if not self.game:
            return

        for nick, player in self.game.players.items():
            if player.state == game.Player.WAITING:
                self.cardinal.sendMsg(nick, "You are picking this round.")
                continue

            hand = []

            # Instructions
            syntax = ['<choice>' for _ in range(self.game.required_cards)]
            syntax.insert(0, '.choose')
            self.cardinal.sendMsg(nick,
                                  "Use {} to make your {}.".format(
                                      ' '.join(syntax),
                                      ('choices'
                                       if len(syntax) > 2
                                       else 'choice'),
                                  ))

            # Hand
            for idx, card in enumerate(player.hand):
                hand.append("[{}] {}".format(idx, card))
            self.cardinal.sendMsg(nick, "Hand: {}".format(' '.join(hand)))

            # Prompt (black card)
            self.cardinal.sendMsg(nick,
                                  "Black card: {} | Player picking: {}"
                                  .format(
                                        self.game.black_card.replace(
                                            '%s', '____'),
                                        self.game.picker.name,
                                  ))

    def show_black_card(self):
        if not self.game:
            return

        self.cardinal.sendMsg(self.channel,
                              "Black card: {} | Player picking: {}"
                              .format(
                                    self.game.black_card.replace('%s', '____'),
                                    self.game.picker.name,
                              ))

    def show_choices(self):
        if not self.game:
            return

        # No blanks, show prompt
        if '%s' not in self.game.black_card:
            self.cardinal.sendMsg(self.channel, self.game.black_card)

        for idx, choice in enumerate(self.game.choices):
            # Send the option
            self.cardinal.sendMsg(self.channel,
                                  " [{}] {}".format(idx, choice[1]))

        self.cardinal.sendMsg(self.channel,
                              "{}: Make your choice with .choose!"
                              .format(self.game.picker.name))

    def send_scores(self):
        if not self.game:
            return

        standing = 0
        if not self.game.scores:
            self.cardinal.sendMsg(self.channel, "Nobody has any points!")
            return

        for name, player in self.game.scores:
            standing += 1
            self.cardinal.sendMsg(self.channel,
                                  "{}. {} - {} points"
                                  .format(standing, name, player.points))

    def finish_game(self):
        if not self.game:
            return

        # log but continue ending the game if scores fail to send
        try:
            self.send_scores()
        except Exception:
            self.logger.exception("Failure sending scores")
            self.cardinal.sendMsg(self.channel,
                                  "I had an issue tallying up scores. :(")

        # Close the game cleanly - still let a new game begin if this fails for
        # some reason
        try:
            self.game.close()
        finally:
            self.game = None

            self.cardinal.sendMsg(self.channel,
                                  "Well played! You may use .play to start a "
                                  "new game.")

    def close(self, cardinal):
        if self.game:
            self.game.close()


def setup(cardinal, config):
    return CAHPlugin(cardinal, config)
