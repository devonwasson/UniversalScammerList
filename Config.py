import praw
import os
import json

def get_json_data(fname):
        with open(fname) as json_data:
                data = json.load(json_data)
        return data

def dump(db, fname):
	with open(fname, 'w') as outfile:  # Write out new data
		outfile.write(json.dumps(db, sort_keys=True, indent=4))

class Config():

	def __init__(self, sub_name):
		self.fname = "config/" + sub_name + ".json"
		self.raw_config = get_json_data(self.fname)

		self.subreddit_name = self.raw_config['subreddit_name'].lower()
		self.client_id = self.raw_config['client_id']
		self.client_secret = self.raw_config['client_secret']
		self.bot_username = self.raw_config['bot_username']
		self.bot_password = self.raw_config['bot_password']
		# If this account has permission to write bans to the USL
		self.write_to = self.raw_config['write_to']
		# If this account has permission to read bans from the USL
		self.read_from = self.raw_config['read_from']
		# Tags that this account is subscribed to
		self.tags = self.raw_config['tags']
		self.reddit = praw.Reddit(client_id=self.client_id, client_secret=self.client_secret, user_agent='USL Bot for ' + self.subreddit_name + ' v1.0 (by u/RegExr)', username=self.bot_username, password=self.bot_password)
		self.subreddit_object = self.reddit.subreddit(self.subreddit_name)


	def is_bot_name(self, bot_name):
		return bot_name.lower() in [self.bot_username.lower(), "uslbot"]

	def update_config(self, tags):
		self.tags = tags
		self.raw_config['tags'] = self.tags
		dump(self.raw_config, self.fname)
