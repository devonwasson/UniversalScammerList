import sys
sys.path.insert(0, '.')
from Config import Config
from tags import TAGS
import wiki_helper

import praw

from collections import defaultdict
import requests
import argparse
import time

request_url = "http://0.0.0.0:8080"

DO_NOT_BAN = set(['[deleted]', 'automoderator'])

def check_if_mod(sub_config):
	return sub_config.bot_username.lower() in sub_config.mods

def clean_ban_tag(tag):
	if tag[0] == "#":
		tag = tag[1:]
	return "#" + "".join([x.lower() for x in tag if x.isalpha()])

def get_ban_tags_and_description(description):
	tags = []
	other = []
	for word in [x for x in description.split(" ") if x]:
		if word[0] == "#":
			tags.append(clean_ban_tag(word))
		else:
			other.append(word)
	description = " ".join(other)
	description = " ".join(description.split(":")[1:])
	return tags, description

def get_mod_actions(sub_config, last_update_time, action='banuser', before=None):
	actions = []
	try:
		if before is not None:
			action_generator = sub_config.subreddit_object.mod.log(limit=None, params={'before':before.id})
		else:
			action_generator = sub_config.subreddit_object.mod.log(limit=None)
	except Exception as e:
		print(sub_config.subreddit_name + " was unable to get mod actions when checking for bans with error " + str(e))
		return actions
	found_last_action = False
	try:
		for action in action_generator:
			if action.created_utc <= last_update_time:
				found_last_action = True
				break
			actions.append(action)
	except Exception as e:
		print(sub_config.subreddit_name + " was unable to continue scraping the mod log with error " + str(e))
		found_last_action = True
	if not found_last_action:
		return actions + get_mod_actions(sub_config, last_update_time, before=actions[-1])
	return actions

def publish_bans(sub_config):
	last_update_time_data = requests.get(request_url + "/get-last-update-time/", data={'sub_name': sub_config.subreddit_name}).json()
	if 'update_time' in last_update_time_data:
		last_update_time = last_update_time_data['update_time']
	else:
		print("Error getting last_update_time from server: " + last_update_time_data['error'])
		return

	# Handle the special case where we don't have a last update time
	if last_update_time == 0:
		last_update_time = time.time() - 1
		new_update_time = time.time()
	else:
		new_update_time = last_update_time

	actions =  get_mod_actions(sub_config, last_update_time)
	for action in actions:
		if action.created_utc > new_update_time:
			new_update_time = action.created_utc
		created_utc = action.created_utc
		description = action.description
		banned_by = action.mod
		banned_user = action.target_author
		# Ignore bans issued by the USL
		if sub_config.is_bot_name(banned_by.name):
			continue
		# Ignore temp bans
		if not str(action.details) == "permanent":
			continue
		ban_tags, description = get_ban_tags_and_description(description)
		# Ignore bans without USL tags
		if not ban_tags:
			continue
		unknown_tags = [tag[1:] for tag in ban_tags if tag[1:] not in TAGS]
		if unknown_tags:
			print("UNKNOWN TAGS: " + ", ".join(unknown_tags))
		print("u/" + banned_user + " has been banned by u/" + banned_by.name + " on r/" + sub_config.subreddit_name + " at " + str(created_utc) + " with tags \#" + ", \#".join(ban_tags) + " with description " + description)
		requests.post(request_url + "/publish-ban/", {'banned_user': banned_user, 'banned_by': banned_by.name, 'banned_on': sub_config.subreddit_name, 'issued_on': created_utc, 'tags': ",".join(ban_tags), 'description': description})

	if last_update_time != new_update_time:
		requests.post(request_url + "/set-last-update-time/", {'sub_name': sub_config.subreddit_name, 'update_time': new_update_time})

def ban_from_queue(sub_config):
	mods = sub_config.mods
	to_ban = requests.get(request_url + "/get-ban-queue/", data={'sub_name': sub_config.subreddit_name}).json()
	users_to_descriptions = defaultdict(lambda: {'description': '', 'mod note': '', 'tags': []})
	for tag in to_ban:
		if tag not in sub_config.tags:
			continue
		for user in to_ban[tag]:
			user_data = to_ban[tag][user]
			if user not in users_to_descriptions:
				users_to_descriptions[user]['mod note'] = "USL ban from r/" + user_data['banned_on'] + " - " + user_data['description'] + " - "
			users_to_descriptions[user]['mod note'] += "#" + tag + " "
			users_to_descriptions[user]['description'] = "You have been banned from r/" + sub_config.subreddit_name + " due to a ban from r/" + user_data['banned_on'] + ". You must contact the mods of r/" + user_data['banned_on'] + " to have this ban removed. Please do not reply to this message."
			users_to_descriptions[user]['tags'].append(tag)

	previously_banned_users = []
	sleep_time = 0
	if len(users_to_descriptions.keys()) > 1000:
		sleep_time = 7.5
	for user in users_to_descriptions:
		text = users_to_descriptions[user]
		if user in DO_NOT_BAN:
			continue
		if user.lower() in mods:
			message_content = "Hello, mods of r/" + sub_config.subreddit_name + ". Recently, u/" + user + " was added to the USL with the following context: \n\n> " + text['mod note'] + "\n\nConsidering this user is a **moderator** of your community, it is **imperative** that you figure out what happened.\n\nIf there was a misunderstanding, please reach out to the mods of r/UniversalScammerList to get this sorted out. However, If this user is no longer fit to be a moderator, they should be removed as a moderator and banned from your community."
			sub_config.subreddit_object.message(subject="One of your moderators has been added to the Universal Scammer List", message=message_content)
			message_content = "Hello, USL Mods. Recently, u/" + user + " was added to the USL with the following context: \n\n> " + text['mod note'] + "\n\nHowever, this user is a moderator of r/" + sub_config.subreddit_name + " which is a USL-participating sub.\n\nPlease look into this matter ASAP. If the user in question is not fit to be a moderator and they are **not** removed from the sub(s) in which they moderate, please remove those sub(s) from the USL."
			sub_config.reddit.subreddit('universalscammerlist').message(subject="Moderator of r/" + sub_config.subreddit_name + " added to the USL", message=message_content)
			continue
		ban_note = "".join([ban.note for ban in sub_config.subreddit_object.banned(redditor=user)]).lower()
		# If the user has a ban note (implying they are banned) and there are not USL tag in the ban note, skip
		if ban_note and not any(["#"+_tag in ban_note for _tag in TAGS]):
			previously_banned_users.append(user)
			continue
		# else if there is a ban for this user and there ARE existing USL tags in the ban notes, silently skip
		# Having a USL ban tag in the description is important for unbanning, but we only check that at least
		# one tag exists to unban because we use the database as the source of truth and not ban notes. As such,
		# as long as one ban note is already present, there is no need to override the ban and do extra work.
		elif ban_note and any(["#"+_tag in ban_note for _tag in TAGS]):
			continue
		try:
			sub_config.subreddit_object.banned.add(user, ban_message=text['description'][:1000], ban_reason="USL Ban", note=text['mod note'][:300])
		except Exception as e:
			deleted_account = False
			try:
				sub_config.reddit.redditor(user).id
			except Exception as e:
				if type(e).__name__ == 'NotFound':
					print(user + " deleted their account so they cannot be banned from " + sub_config.subreddit_name)
					deleted_account = True
			if not deleted_account:
				print("Unable to ban u/" + user + " on r/" + sub_config.subreddit_name + " with error " + str(e))
				requests.post(request_url + "/add-to-action-queue/", {'sub_name': sub_config.subreddit_name, 'username': user, 'action': 'ban', 'tags': ",".join(users_to_descriptions[user]['tags'])})
		if sleep_time > 0:
			time.sleep(sleep_time)
	if previously_banned_users:
		message_content = "Hello, mods of r/" + sub_config.subreddit_name + ". Recently, the folling users were added to the USL:\n\n* u/" + "\n\n* u/".join(previously_banned_users) + "\n\nHowever, this user was previously banned on your subreddit through unrelated means. At this time, no action is required. The ban against this user on your sub is not being modified.\n\nHowever, if you wish to modify this ban to be in line with the USL, please modify the ban for this user to include the tags mentioned above. This will sync your ban with the USL so, if this user is taken off the USL in the future, they will be unbanned from your sub as well. If you do NOT wish for this to happen and want this user to remain banned, even if they are removed from the USL, then no action is needed on your part."
		# Send the message as the log bot to avoid spamming mod discussion
		Config('logger').reddit.subreddit(sub_config.subreddit_name).message(subject="Duplicate Ban Found By USL", message=message_content)

def get_messages(sub_config):
	messages = []
	to_mark_as_read = []
	try:
		for message in sub_config.reddit.inbox.unread():
			to_mark_as_read.append(message)
			if not message.was_comment:
				if 'gadzooks! **you are invited to become a moderator**' in message.body.lower() and message.subreddit != None and message.subreddit.display_name.lower() == sub_config.subreddit_name:
					try:
						sub_config.subreddit_object.mod.accept_invite()
					except Exception as e:
						print("Was unable to accept invitation to moderate " + sub_config.subreddit_name + " with error " + str(e))
				else:
					messages.append(message)
	except Exception as e:
		print(e)
		print("u/" + sub_config.bot_username + " failed to get next message from unreads. Ignoring all unread messages and will try again next time.")
		return []

	for message in to_mark_as_read:
		try:
			message.mark_read()
		except Exception as e:
			print(e)
			print("Unable to mark message as read. Leaving it as is.")

	return messages

def publish_unbans(sub_config, messages):
	for message in messages:
		try:
			requester = message.author.name.lower()
		except AttributeError as e:  # Messages without names aren't worth checking
			continue
		text = message.body.strip().lower()
		words = text.split(" ")
		unbanned_user = ""
		tags = []
		command = ""
		for count, word in enumerate(words):
			word = word.strip()
			if not word:
				continue
			if word == "$unban":
				command = word
				if count + 1 < len(words):
					unbanned_user = words[count+1].split("/")[-1]
			elif word[0] == "#":
				tags.append(word[1:])
		# Don't want to start a PM war with my own bots.
		if 'kofi.regexr.tech' in text:
			continue
		if not command:
			text = "No command was found. Please be sure to start your message with a command. Commands should be in the form `$command`. For example, `$unban u/username #tag1 #tag2`"
		elif command == "$unban":
			if not unbanned_user:
				text = "No username was found following the command in your message. Please ensure that a username is present in your message. For example, `$unban u/username #tag1 #tag2`"
			elif not tags:
				text = "No tags were found in your message. Please ensure that tags start with a `#` character and include the tags you wish to remove from the USL. For example, `$unban u/username #tag1 #tag2`"
			else:
				# Send unban request to server. Check response for errors, like user not banned, or tag not recognized
				response = requests.post(request_url + "/publish-unban/", {'requester': requester, 'unbanned_user': unbanned_user, 'tags': ",".join(tags)}).json()
				if 'error' in response:
					text = response['error']
				else:
					text = "u/" + unbanned_user + " is being unbanned with the following tags: " + ", ".join(["#"+tag for tag in tags])
		else:
			text = "Handling for that command has not been implimented yet. Sorry."

		try:
			message.reply(body=text)
		except Exception as e:
			print(sub_config.bot_username + " could not reply to u/" + str(message.author) + " with error - " + str(e))

def unban_from_queue(sub_config):
	to_unban = requests.get(request_url + "/get-unban-queue/", data={'sub_name': sub_config.subreddit_name, 'tags': ",".join(sub_config.tags)}).json()
	users = []
	for tag in to_unban:
		users += to_unban[tag]
	for user in list(set(users)):
		ban_note = "".join([ban.note for ban in sub_config.subreddit_object.banned(redditor=user)]).lower()
		if ban_note and not any(["#"+_tag in ban_note for _tag in TAGS]):
			message_content = "Hello, mods of r/" + sub_config.subreddit_name + ". Recently, u/" + user + " was removed from the USL. However, you banned this user for unrelated reasons. As such, I will not remove this ban for you. However, if you banned this user because you believed them to be a scammer, please double check things as the situation might have changed. Thanks!"
			Config('logger').reddit.subreddit(sub_config.subreddit_name).message(subject="Conflicting Unban Found In The USL", message=message_content)
			continue
		try:
			sub_config.subreddit_object.banned.remove(user)
		except Exception as e:
			print("Unable to unban u/" + user + " on r/" + sub_config.subreddit_name + " with error " + str(e))
			_tags = [tag for tag in to_unban.keys() if user in to_unban[tag]]
			requests.post(request_url + "/add-to-action-queue/", {'sub_name': sub_config.subreddit_name, 'username': user, 'action': 'unban', 'tags': ",".join(_tags)})

def main():
	parser = argparse.ArgumentParser()
	parser.add_argument('sub_name', metavar='C', type=str)
	args = parser.parse_args()

	sub_config = Config(args.sub_name.lower())
	try:
		sub_config.mods = [x.name.lower() for x in sub_config.subreddit_object.moderator()]
	except Exception as e:
		print("    u/" + sub_config.bot_username + " was unable to get list of moderators from r/" + sub_config.subreddit_name + " with error " + str(e) + ". Skipping iteration...")
		return

	# Accepts mod invites and returns unban requests
	messages = get_messages(sub_config)

	if not check_if_mod(sub_config):
		return

	wiki_helper.run_config_checker(sub_config)

	if sub_config.write_to:
		publish_bans(sub_config)
		publish_unbans(sub_config, messages)
	if sub_config.read_from:
		ban_from_queue(sub_config)
		unban_from_queue(sub_config)


if __name__ == "__main__":
	main()
