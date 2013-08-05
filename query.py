import time
import signal
import inspect
import threading

from OSC import *
from live.object import *

def singleton(cls):
	instances = {}
	def getinstance(*args):
		if cls not in instances:
			instances[cls] = cls(*args)
		return instances[cls]
	return getinstance

#------------------------------------------------------------------------
# Helper methods to save instantiating an object when making calls.
#------------------------------------------------------------------------

def query(*args, **kwargs):
	return Query().query(*args, **kwargs)

def query_one(*args, **kwargs):
	return Query().query_one(*args, **kwargs)

def cmd (*args, **kwargs):
	Query().cmd(*args, **kwargs)

@singleton
class Query(LoggingObject):
	def __init__(self):
		self.indent = 0
		self.beat_callback = None
		self.listening = False
		self.listen_port = 9001

		self.osc_client = OSCClient()
		self.osc_client.connect(("localhost", 9000))
		self.osc_server = OSCServer(("localhost", self.listen_port))
		self.osc_server_thread = None
		self.osc_read_event = None

		self.response_address = None

	def __str__(self):
		return "live.query"

	def stop(self):
		if self.listening:
			self.osc_server.close()
			self.listening = False

	def listen(self):
		try:
			self.trace("started listening")
			self.osc_server.addMsgHandler("default", self.handler)
			self.osc_server_thread = threading.Thread(target = self.osc_server.serve_forever)
			self.osc_server_thread.setDaemon(True)
			self.osc_server_thread.start()
			self.listening = True
		except Exception, e:
			self.warn("listen failed (couldn't bind to port %d): %s" % (self.listen_port, e))

	def cmd(self, msg, *args):
		# send msg without expected response
		msg = OSCMessage(msg)
		msg.extend(list(args))
		self.osc_client.send(msg)

	def query(self, msg, *args, **kwargs):
		#------------------------------------------------------------------------
		# use **kwargs because we want to be able to specify an optional kw
		# arg after variable-length args -- 
		# eg live.query("/set/freq", 440, 1.0, response_address = "/verify/freq")
		# http://stackoverflow.com/questions/5940180/python-default-keyword-arguments-after-variable-length-positional-arguments
		#------------------------------------------------------------------------
		if not self.listening:
			self.listen()

		#------------------------------------------------------------------------
		# some calls produce responses at different addresses
		# (eg /live/device -> /live/deviceall). specify a response_address to
		# take account of this.
		#------------------------------------------------------------------------
		response_address = kwargs.get("response_address", None)
		if response_address:
			self.response_address = response_address
		else:
			self.response_address = msg

		self.query_rv = []

		self.osc_server_event = threading.Event()

		msg = OSCMessage(msg)
		msg.extend(list(args))
		self.osc_client.send(msg)

		rv = self.osc_server_event.wait(5)
		if not rv:
			print "*** timed out waiting for server response"

		return self.query_rv

	def query_one(self, msg, *args):
		rv = self.query(msg, *args)
		if not rv:
			return None
		return rv[0]

	def handler(self, address, tags, data, source):
		# print "handler: %s %s" % (address, data)
		if address == self.response_address:
			self.query_rv += data
			self.osc_server_event.set()
			return

		if address == "/live/beat":
			if self.beat_callback is not None:
				#------------------------------------------------------------------------
				# Beat callbacks are used if we want to trigger an event on each beat,
				# to synchronise with the timing of the Live set.
				#
				# Callbacks may take one argument: the current beat count.
				# If not specified, call with 0 arguments.
				#------------------------------------------------------------------------
				# It might be nice to send the current beat # as a parameter, but we
				# also want to be able to handle callbacks with no args -- TODO: look
				# into this.
				#------------------------------------------------------------------------
				# argspec = inspect.getargspec(self.beat_callback)
				# if len(argspec.args) > 0:
				#	self.beat_callback(data[0])
				#------------------------------------------------------------------------
				self.beat_callback()