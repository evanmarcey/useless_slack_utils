import logging
import time
import random
from slackclient import SlackClient
import giphypop

from src.str_utils import find_element_in_string, strip_punctuation
from src.misc_utils import load_homophones
from src import exceptions

logger = logging.getLogger()
logging.basicConfig()
logger.setLevel(logging.DEBUG)


class SlackEventHandler:

    def __init__(self,
                 slack_token,
                 random_reply_flg=False,
                 random_gif_flg=False,
                 set_typing_flg=False,
                 mark_read_flg=False,
                 someones_talking_about_you_flg=False,
                 magic_eight_flg=False,
                 homophone_flg=False,
                 run_level="DM Only",
                 users=None,
                 responses=None,
                 stay_channel=None,
                 init_homophones=None
                 ):
        """
        :param slack_token: (str) API token to connect to Slack
        :param random_reply_flg: (Bool) True if you want the handler to perform the random_reply handling
        :param random_gif_flg: (Bool) True if you want the handler to turn your random replies into gifs
        :param set_typing_flg: (Bool) True if you want the handler to perform the set_typing handling
        :param mark_read_flg: (Bool) True if you want the handler to perform the mark_read handling
        :param someones_talking_about_you_flg: (Bool) True if you want the handler to perform someones_talking_about_you
            handling
        :param magic_eight_flg: (Bool) True if you want the handler to perform magic_eight handling
        :param homophone_flg: (Bool) True if you want the handler to perform homophone_suggest
        :param run_level: (str) Works on 3 levels: DM Only (only direct messages), Private (dms and private channels),
            and all
        :param users: ([str]) List of users for whom events should be handled, or 'All'; defaults to None
        :param responses: ([str]) If using the random_reply, this is the list of custom responses
        :param stay_channel: (str) channel to use if you're doing someones_talking_about_you
        :param init_homophones: (dict) override dictionary of homophones to use
        """
        self.slack_token = slack_token
        self.handler_flags = {
            'random_reply_flg': random_reply_flg,
            'random_gif_flg': random_gif_flg,
            'set_typing_flg': set_typing_flg,
            'mark_read_flg': mark_read_flg,
            'someones_talking_about_you_flg': someones_talking_about_you_flg,
            'magic_eight_flg': magic_eight_flg,
            'homophone_flg': homophone_flg
        }

        self.run_level = run_level
        if users == 'All':
            sc = SlackClient(self.slack_token)
            sc.rtm_connect()
            self.users = [user['id'] for user in sc.api_call("users.list")['members']]
        else:
            self.users = users
        if responses:
            self.responses = responses
        else:
            # default responses if none provided
            self.responses = [
                'Wow! That\'s so interesting!',
                'What hilarious hijinx you\'ve been getting up to!',
                'Where has the time gone?',
                'Curious',
                'I\'ve never thought of it that way.',
                'I\'ll keep that in mind.',
                'Thanks for letting me know.',
                'I\'ll be sure to follow up on that.'
            ]
        self.stay_channel = stay_channel
        if homophone_flg:
            self.homophones = load_homophones(init_homophones)
        else:
            self.homophones = None

    def update_flag(self, flag_name, flag_value):
        """
        Updates the value for the given flag

        :param flag_name: (str) name of flag to update
        :param flag_value: (str) new value for flag
        :return:
        """

        try:
            if flag_name not in self.handler_flags.keys():
                message = "\n{f} is not in list of flags.\nAcceptable flag names are: {n}.".\
                    format(f=flag_name,
                           n=', '.join(self.handler_flags.keys()))
                raise exceptions.InvalidFlagNameException(message=message)
            self.handler_flags[flag_name] = flag_value

            if flag_name == 'homophone_flg' and flag_value:
                self.homophones = load_homophones()
            else:
                self.homophones = None

        except exceptions.InvalidFlagNameException as e:
            logger.error(e.message)
            raise

    def add_responses(self,new_responses):
        """
        Add 1+ responses for the random_reply method

        :param new_responses: 2 possible types:
            - str: single response to add
            - list: multiple responses to add
        :return:
        """
        try:
            if type(new_responses) == str and new_responses not in self.responses:
                self.responses.append(new_responses)
            elif type(new_responses) == list:
                self.responses += new_responses
                self.responses = list(set(self.responses))
            else:
                msg = "Passed data type {dt} to method 'add_responses.' Only str or list allowed.".\
                    format(dt=type(new_responses))
                raise exceptions.TypeNotHandledException(msg)
        except exceptions.TypeNotHandledException as e:
            logger.error(e.message)
            raise


    def begin(self, length=-1):
        """
        begin kicks of the event handling process

        :param length: (int) Number of seconds to continue loop; -1 if should not end
        :return: None
        """

        sc = SlackClient(self.slack_token)

        try:
            if sc.rtm_connect():
                # get list of all users
                all_users = [
                    {
                        'name': user['name'],
                        'id': user['id'],
                        'first_name': user['profile']['first_name'],
                        'last_name': user['profile']['last_name']
                    }
                    for user in sc.api_call("users.list")['members']
                    if 'first_name' in user['profile'].keys() and 'last_name' in user['profile'].keys()]

                start_time = time.time()

                # connect to server and start monitoring
                while sc.server.connected and (time.time() <= start_time+length or length == -1):
                    event = sc.rtm_read()

                    try:
                        if event:
                            logger.debug(event)

                            # check event type and determine if action should be taken
                            msg_type = self.get_msg_type(sc, event)
                            logger.debug(msg_type)
                            if (self.run_level == 'DM Only' and msg_type == 'IM') or \
                                (self.run_level == 'Private' and msg_type != 'Public') or\
                                    self.run_level == 'All':

                                # if message is in correct scope, perform designated tasks
                                if self.handler_flags['random_reply_flg']:
                                    self.random_reply(sc, event)
                                if self.handler_flags['mark_read_flg']:
                                    self.mark_read(sc, event, msg_type)
                                if self.handler_flags['someones_talking_about_you_flg']:
                                    self.someones_talking_about_you(sc, event, msg_type, all_users)
                                if self.handler_flags['magic_eight_flg']:
                                    self.magic_eight(sc, event)
                                if self.handler_flags['homophone_flg']:
                                    self.homophone_suggest(sc, event)
                            else:
                                logger.debug("Message not in scope.")
                        time.sleep(1)

                    except KeyError:
                        logger.debug("Ignore this event: " + str(event))

                if time.time() > start_time + length:
                    logger.debug("Event handling completed.\nStopping Slack monitor.")
        except KeyboardInterrupt:
            logger.debug("Stopping Slack monitor.")
            raise

    def get_msg_type(self, sc, event):
        """
        get_msg_type determines if a message event if private, public or an IM

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the random_reply
        :return: type of message (Public, Private or IM)
        """
        im_info = sc.api_call("im.info", channel=event[0]['channel'])
        if 'ok' in im_info.keys() and im_info['ok'] is False:
            dm_info = sc.api_call("groups.info", channel=event[0]['channel'])
            if 'ok' in dm_info.keys() and dm_info['ok'] is False:
                return 'Public'
            else:
                return 'Private'
        else:
            return 'IM'

    def random_reply(self, sc, event):
        """
        For a given message event,
        random_reply sends a random message from the list if responses.
        If gif is enabled, sends the top result for that response from giphy

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the random_reply
        :return:
        """

        try:
            if event and \
                event[0]['type'] == 'message' and \
                    (event[0]['user'] in self.users):
                randint = random.randint(0, len(self.responses) - 1)

                message = self.responses[randint]
                if self.handler_flags['random_gif_flg']:
                    g = giphypop.Giphy()
                    message = "{m}\n{v}".format(
                        v=[x for x in g.search(message)][0],
                        m=message)

                sc.rtm_send_message(event[0]['channel'], message)

        except KeyError:
            if 'type' not in event[0].keys():
                logger.debug("Don't worry about this one.")
                logger.debug(event)
            else:
                raise

    def mark_read(self, sc, event, msg_type):
        """
        For a given message event, if the event has a user notification tag, but it does not contain the user's name
        mark_read marks the channel as read up to that point

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the mark_read
        :param msg_type: type of message
        :return:
        """
        try:
            if event[0]['type'] == 'message':

                text = event[0]['text']

                if find_element_in_string(text, '<') != -1 and \
                        find_element_in_string(text, '>') != -1 and \
                        find_element_in_string(text, sc.server.username) == -1:
                    if msg_type == 'IM':
                        sc.api_call("im.mark", channel=event[0]['channel'], ts=event[0]['ts'])
                    elif msg_type == 'Private':
                        sc.api_call("groups.mark", channel=event[0]['channel'], ts=event[0]['ts'])
                    else:
                        sc.api_call("channels.mark", channel=event[0]['channel'], ts=event[0]['ts'])
                else:
                    logger.debug('Don\'t change')

        except KeyError:
            if 'type' not in event[0].keys():
                logger.debug("Don't worry about this one.")
                logger.debug(event)
            else:
                raise

    def someones_talking_about_you(self, sc, event, msg_type, all_users):
        """
        For a given message event, if a user's full name is found in the message text
        someones_talking_about_you sends a message to a notify channel which tags the person talked about,
        the people in the private channel, and tells the full body of the message

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the mark_read
        :param msg_type: type of message
        :param all_users: all users in slack environment
        :return:
        """

        try:
            users_to_notify = []

            if event[0]['type'] == 'message' and msg_type != 'Public':
                text = event[0]['text']
                for user in all_users:
                    if find_element_in_string(text.lower(),
                                              user['first_name'].lower() + ' ' + user['last_name'].lower()) != -1 :
                        users_to_notify.append(user)

                if len(users_to_notify) > 0:
                    user_ids = [user['id'] for user in users_to_notify]

                    not_all_users_in_convo = False
                    convo_members = sc.api_call("conversations.members", channel=event[0]['channel'])
                    for user in user_ids:
                        if user not in [cv for cv in convo_members['members']]:
                            not_all_users_in_convo = True

                    if not_all_users_in_convo:
                        message = """Hey <@{u}> 
                        
                        <@{c}> were talking about you in a private message!
                        
                        Here's what <@{s}> said:
                        
                        {t}
                        """.format(u="> <@".join(user_ids),
                                   c="> <@".join([cv for cv in convo_members['members']]),
                                   s=event[0]['user'],
                                   t=text)

                        sc.rtm_send_message(self.stay_channel, message)

        except KeyError:
            if 'type' not in event[0].keys():
                logger.debug("Don't worry about this one.")
                logger.debug(event)
            else:
                raise

    def magic_eight(self, sc, event):
        """
        For a given message event, if a '?' is found in the message
        magic_eight sends one of the top 10 magic 8 ball gifs from giphy as a message

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the random_reply
        :return:
        """
        try:
            if event and \
                event[0]['type'] == 'message' and \
                    (event[0]['user'] in self.users):
                randint = random.randint(0, 10)
                if find_element_in_string(event[0]['text'], '?') >= 0:
                    g = giphypop.Giphy()
                    message = "{v}\n".format(v=[x for x in g.search('magic eight ball')][randint])
                    logger.debug("TEXT: "+event[0]['text'])
                    sc.rtm_send_message(event[0]['channel'], message)
                else:
                    logger.debug("No question mark found")

        except KeyError:
            if 'type' not in event[0].keys():
                logger.debug("Don't worry about this one.")
                logger.debug(event)
            else:
                raise

    def homophone_suggest(self, sc, event):
        """
        For a given message event and for every homophone found in the message,
        homophone_suggest sends a message suggesting the opposite homophone

        :param sc: SlackClient used to connect to server
        :param event: event to be handled by the random_reply
        :return: None
        """
        try:
            text_words = [strip_punctuation(word) for word in
                          event[0]['text'].lower().split(' ')
                          if strip_punctuation(word) in self.homophones.keys()]

            for word in text_words:
                message = "Hey <@{u}>!\n\tYou typed {k}, but you probably meant {v}.".\
                    format(u=event[0]['user'],
                           k=word,
                           v=self.homophones[word])
                sc.rtm_send_message(event[0]['channel'], message)

        except KeyError:
            if 'type' not in event[0].keys():
                logger.debug("Don't worry about this one.")
                logger.debug(event)
            else:
                raise
