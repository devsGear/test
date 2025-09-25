import sys
import socket
import threading
import queue
import concurrent.futures
import time

# Default server settings
SERVER = '127.0.0.1'  # This is localhost - my own computer!
PORT = 8080          # Port number above 1024 (since below that requires admin)
THREADPOOL = 10      # Number of worker threads
FORMAT = 'utf-8'     # Encoding for strings

# Function to show how to use the server program
def print_usage():
    """This function prints how to use our server from command line"""
    print("*** HTTP Server Usage Instructions ***")
    print(f"Run the server like this: python {sys.argv[0]} [PORT] [HOST] [THREADPOOL]")
    print(f"  PORT: Which port to use (default: {PORT})")
    print(f"  HOST: Which IP to bind to (default: {SERVER})")
    print(f"  THREADPOOL: How many threads to use (default: {THREADPOOL})")
    print(f"Example: python {sys.argv[0]} 8000 0.0.0.0 20")
    print("(0.0.0.0 means 'listen on all network interfaces')")

# Get command line arguments
# I learned about try-except to handle errors!
try:
    # Check if user asked for help
    if len(sys.argv) > 1:
        if sys.argv[1] in ['-h', '--help', 'help']:
            print_usage()
            sys.exit(0)
        # First argument is port number
        PORT = int(sys.argv[1])  # Convert string to integer
    
    # Second argument is host address
    if len(sys.argv) > 2:
        SERVER = sys.argv[2]
    
    # Third argument is thread pool size
    if len(sys.argv) > 3:
        THREADPOOL = int(sys.argv[3])
except ValueError as e:
    # This happens if user types letters instead of numbers
    print(f"Oops! Something went wrong with your arguments: {e}")
    print_usage()
    sys.exit(1)
        
# Put together the address - this is a tuple (learned about these in class!)
ADDR = (SERVER, PORT)

# Create a queue to store waiting connections
# This is cool - it lets us handle connections in order
connection_queue = queue.Queue()

# Create a lock for printing
# This prevents garbled output when multiple threads print at once
print_lock = threading.Lock()

def safe_print(message):
    """Print messages safely from multiple threads
    
    The lock makes sure only one thread prints at a time
    """
    with print_lock:  # This is like a mutex we learned about in OS class
        print(message)

def parse_http_request(request_data):
    """Extract important info from the HTTP request
    
    This function breaks down the raw HTTP data into useful parts
    """
    # Check if we got any data at all
    if not request_data:
        return None, {}
    
    # HTTP requests have lines separated by \r\n
    # Need to decode bytes to string first
    lines = request_data.decode(FORMAT, errors='ignore').split('\r\n')
    if not lines:
        return None, {}
    
    # First line has the request type (GET, POST, etc.)
    request_line = lines[0]  # e.g. "GET / HTTP/1.1"
    
    # Headers are in format "Name: Value"
    headers = {}
    for line in lines[1:]:  # Skip the first line
        if not line:  # Empty line means end of headers
            break
        if ':' in line:
            # Split at first colon
            key, value = line.split(':', 1)
            # Store header name in lowercase for easy comparison
            headers[key.strip().lower()] = value.strip()
            
    return request_line, headers

def handleClient(conn, addr):
    """Process one client connection
    
    This function:
    1. Receives the HTTP request
    2. Sends back our HTML file
    3. Handles persistent connections
    """
    # Log that we got a new connection
    safe_print(f"[NEW CONNECTION] Client at {addr} connected")
    
    try:
        # Set a timeout so the connection doesn't hang forever
        # I learned about timeouts in networking class!
        conn.settimeout(30)
        
        # Get the client's request
        request_data = conn.recv(1024)  # Read up to 1024 bytes
        
        # Parse the request to get headers
        request_line, headers = parse_http_request(request_data)
        
        # Check if client wants a persistent connection
        # HTTP/1.1 uses keep-alive by default
        connection_type = headers.get('connection', '').lower()
        persistent = 'keep-alive' in connection_type
        
        # Print what kind of request we got
        safe_print(f"[REQUEST] {request_line} {'(persistent)' if persistent else '(will close after response)'}")
        
        # Read our HTML file
        # TODO: In the future, check which file the client requested!
        try:
            with open('index.html', 'r') as file:
                http_content = file.read()
        except FileNotFoundError:
            # If file doesn't exist, send a simple message
            http_content = "<html><body><h1>File not found</h1></body></html>"
            safe_print("[ERROR] index.html not found!")
        
        # Create the HTTP response header
        # This is the format from the HTTP specification
        if persistent:
            connection_header = "Connection: keep-alive\r\n"
        else:
            connection_header = "Connection: close\r\n"
        
        http_header = (
            "HTTP/1.1 200 OK\r\n"  # Status line
            "Content-Type: text/html\r\n"  # Type of content
            f"Content-Length: {len(http_content)}\r\n"  # Length in bytes
            f"{connection_header}"  # Whether to keep connection open
            "\r\n"  # Empty line separates headers from body
        )
        
        # Combine header and content
        http_response = http_header + http_content
        
        # Send the response to client
        conn.send(http_response.encode(FORMAT))
        
        # If it's a persistent connection, wait for more requests
        if persistent:
            # Use a shorter timeout for follow-up requests
            conn.settimeout(5)
            
            # Keep connection open for more requests
            while True:
                try:
                    # Try to get another request
                    request_data = conn.recv(1024)
                    if not request_data:  # Client closed connection
                        safe_print(f"[INFO] Client {addr} closed connection")
                        break
                    
                    # For simplicity, just send the same response
                    # In a real server, we'd parse the new request properly
                    safe_print(f"[REQUEST] Another request from {addr} (persistent connection)")
                    conn.send(http_response.encode(FORMAT))
                    
                except socket.timeout:
                    # No more requests within timeout period
                    safe_print(f"[TIMEOUT] No more requests from {addr}, closing connection")
                    break
                except Exception as e:
                    safe_print(f"[ERROR] Something went wrong with {addr}: {e}")
                    break
    except Exception as e:
        # Something went wrong handling this client
        safe_print(f"[ERROR] Problem with client {addr}: {e}")
    finally:
        # Always close the connection when we're done
        conn.close()
        safe_print(f"[CLOSED] Connection with {addr} closed")

def process_queue():
    """Thread function that processes clients from the queue
    
    Each worker thread runs this function to take clients from the queue
    """
    # Keep running until told to stop
    while True:
        try:
            # Try to get a client from the queue
            # block=False means don't wait if queue is empty
            client_data = connection_queue.get(block=False)
            
            # None is our signal to stop the thread
            if client_data is None:
                safe_print("[WORKER] Worker thread shutting down")
                break
                
            # Unpack the client data
            client_socket, client_addr, queued_time = client_data
            
            # Calculate how long this client waited
            wait_time = time.time() - queued_time
            
            # Log that we're handling this client now
            safe_print(f"[DEQUEUED] Client {client_addr} is being handled (waited {wait_time:.2f} seconds)")
            
            # Process the client
            handleClient(client_socket, client_addr)
            
        except queue.Empty:
            # Queue is empty, wait a bit before checking again
            # This prevents using 100% CPU in a tight loop
            time.sleep(0.1)
        except Exception as e:
            # Something unexpected happened
            safe_print(f"[ERROR] Worker thread error: {e}")

def startServer():
    """Main function to start the server
    
    This function:
    1. Creates the socket
    2. Sets up the thread pool
    3. Accepts client connections
    """
    try:
        # Create a TCP socket
        # AF_INET = IPv4, SOCK_STREAM = TCP
        safe_print("[SETUP] Creating server socket...")
        serverSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        
        # Set SO_REUSEADDR to avoid "Address already in use" errors
        # This lets us restart the server quickly
        serverSocket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        
        # Bind the socket to our address and port
        safe_print(f"[SETUP] Binding to {SERVER}:{PORT}...")
        serverSocket.bind(ADDR)
        
        # Start listening for connections
        # The number 50 is how many connections can wait
        safe_print("[SETUP] Starting to listen...")
        serverSocket.listen(50)
        
        # Show that we're ready
        safe_print(f"[STARTING] Server is starting...")
        safe_print(f"[LISTENING] Server is listening on {SERVER}:{PORT}")
        safe_print(f"[THREADPOOL] Using {THREADPOOL} worker threads")
        
        # Create a thread pool
        # This is so cool - we learned about thread pools in class!
        safe_print("[SETUP] Creating thread pool...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=THREADPOOL) as executor:
            # Start the worker threads
            safe_print("[SETUP] Starting worker threads...")
            for i in range(THREADPOOL):
                executor.submit(process_queue)
                safe_print(f"[WORKER] Started worker thread #{i+1}")
            
            # Main loop: accept connections and add to queue
            safe_print("[READY] Server is ready to accept connections!")
            try:
                while True:
                    # Accept waits for a client to connect
                    client_socket, client_addr = serverSocket.accept()
                    current_time = time.time()
                    
                    # Add the new client to our queue with timestamp
                    connection_queue.put((client_socket, client_addr, current_time))
                    safe_print(f"[QUEUED] New client {client_addr} added to queue")
                    
            except KeyboardInterrupt:
                # User pressed Ctrl+C
                safe_print("[STOPPING] Received shutdown signal (Ctrl+C)")
            finally:
                # Tell all worker threads to stop
                safe_print("[CLEANUP] Stopping all worker threads...")
                for _ in range(THREADPOOL):
                    connection_queue.put(None)
    except Exception as e:
        # Something went wrong starting the server
        safe_print(f"[CRITICAL ERROR] Server couldn't start: {e}")
    finally:
        # Make sure to close the server socket
        if 'serverSocket' in locals():
            serverSocket.close()
            safe_print("[CLEANUP] Server socket closed")

# This is the entry point of our program
if __name__ == "__main__":
    print("=======================================")
    print("= Simple HTTP Server - College Project =")
    print("=======================================")
    startServer()
    
    
    




