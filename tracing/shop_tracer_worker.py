from shop_tracer import ShopTracer
import trace_logger
import common_actors
import user_data

import os, logging, mongoengine, time, threading, pika, configparser
import json


class Worker(threading.Thread):
    def __init__(self, config):
        threading.Thread.__init__(self)

        # 1. Create ShopTracer
        logger = trace_logger.MongoDbTraceLogger()
        self.tracer = ShopTracer(user_data.get_user_data, headless=False, trace_logger = logger)
        common_actors.add_tracer_extensions(self.tracer)
        
        # 2. Connect to RabbitMQ
        rabbitmq_host = config.get('rabbitmq', 'servers', fallback='localhost')
        rabbitmq_queue = config.get('rabbitmq', 'queue', fallback='trace_tasks')
        
        params = pika.ConnectionParameters(host=rabbitmq_host,
            heartbeat_interval=0, connection_attempts=20, retry_delay=1)
        
        self.connection = pika.BlockingConnection(params)
        self.channel = self.connection.channel()
        self.channel.queue_declare(queue = rabbitmq_queue)
        self.channel.basic_qos(prefetch_count = 1)
        self.channel.basic_consume(self.process_task, queue = rabbitmq_queue)        

    def run(self):
        self.channel.start_consuming()
    
    def process_task(self, ch, method, properties, body):
        try:
            # 1. Extract values from task
            task = json.loads(body)
            url = task['url']
            attempts = task.get('attempts', 3)

            # 2. Run Tracing
            status = self.tracer.trace(url, attempts = attempts)

            # 3. If Success, Ack Message Queue
            self.channel.basic_ack(delivery_tag = method.delivery_tag)

        except:
            logger = logging.getLogger("shop_tracer")
            logger.exception('Cannot process task: {}. Rejecting RabbitMQ task.'.format(body))

            ch.basic_nack(delivery_tag = method.delivery_tag, requeue = False)
            
        


config = configparser.ConfigParser()
config.read('config.ini')

# Number of threads
num_threads = config.getint('common', 'num_threads', fallback=8)

# Needs to Selenium otherwise it could hang
os.environ['DBUS_SESSION_BUS_ADDRESS'] = '/dev/null'

# Config Logger
logger = logging.getLogger('shop_tracer')
logger.setLevel(logging.WARNING)
handler = logging.StreamHandler()
formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# Connect to MongoDB
mongo_db = config.get('mogodb', 'db', fallback='trace_automation')
mongoengine.connect(mongo_db)

# Start Workers
workers = []
for _ in range(num_threads):
    worker = Worker(config)
    worker.setDaemon(True)
    workers.append(worker)
    worker.start()

# Keep Main thread for additional checks later
while True:
    # Will do additional checks
    time.sleep(10)