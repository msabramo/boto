# Copyright (c) 2011 Mitch Garnaat http://garnaat.org/
# Copyright (c) 2011, Eucalyptus Systems, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish, dis-
# tribute, sublicense, and/or sell copies of the Software, and to permit
# persons to whom the Software is furnished to do so, subject to the fol-
# lowing conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
# OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABIL-
# ITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT
# SHALL THE AUTHOR BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
# IN THE SOFTWARE.

class Event(object):
    """
    A status event for an instance.

    :ivar code: A string indicating the event type.
    :ivar description: A string describing the reason for the event.
    :ivar not_before: A datestring describing the earliest time for
        the event.
    :ivar not_after: A datestring describing the latest time for
        the event.
    """

    def __init__(self, code=None, description=None,
                 not_before=None, not_after=None):
        self.code = code
        self.description = description
        self.not_before = not_before
        self.not_after = not_after
        
    def __repr__(self):
        return 'Event:%s' % self.code

    def startElement(self, name, attrs, connection):
        return None

    def endElement(self, name, value, connection):
        if name == 'code':
            self.code = value
        elif name == 'description':
            self.description = value
        elif name == 'notBefore':
            self.not_before = value
        elif name == 'notAfter':
            self.not_after = value
        else:
            setattr(self, name, value)

class EventSet(list):
    
    def startElement(self, name, attrs, connection):
        if name == 'item':
            event = Event()
            self.append(event)
            return event
        else:
            return None

    def endElement(self, name, value, connection):
        setattr(self, name, value)

class InstanceStatus(object):
    """
    Represents an EC2 Instance status as reported by
    DescribeInstanceStatus request.

    :ivar id: The instance identifier.
    :ivar zone: The availability zone of the instance.
    :ivar events: A list of events relevant to the instance.
    :ivar state_code: An integer representing the current state
        of the instance.
    :ivar state_name: A string describing the current state
        of the instance.
    """
    
    def __init__(self, id=None, zone=None, events=None,
                 state_code=None, state_name=None):
        self.id = id
        self.zone = zone
        self.events = events
        self.state_code = state_code
        self.state_name = state_name

    def __repr__(self):
        return 'InstanceStatus:%s' % self.id

    def startElement(self, name, attrs, connection):
        if name == 'eventsSet':
            self.events = EventSet()
            return self.events
        else:
            return None

    def endElement(self, name, value, connection):
        if name == 'instanceId':
            self.id = value
        elif name == 'availabilityZone':
            self.zone = value
        elif name == 'code':
            self.state_code = int(value)
        elif name == 'name':
            self.state_name = value
        else:
            setattr(self, name, value)

class InstanceStatusSet(list):

    def __init__(self, connection=None):
        self.connection = connection
        list.__init__(self)
    
    def startElement(self, name, attrs, connection):
        if name == 'item':
            status = InstanceStatus()
            self.append(status)
            return status
        else:
            return None

    def endElement(self, name, value, connection):
        setattr(self, name, value)

