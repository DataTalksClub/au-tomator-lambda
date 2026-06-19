
class Logger():

    def print(self, message):
        print(message.replace('\n', ' ').replace('\r', ' '))

    def info(self, message):
        self.print(message)

    def error(self, message):
        self.print(message)

    def debug(self, message):
        self.print(message)

    def exception(self, message):
        self.print(message)


logger = Logger()
