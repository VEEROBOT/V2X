"""
Lyra Bridge - Serial Transport Layer (THREAD-SAFE VERSION)
Handles UART communication with STM32 controller with auto-reconnect.

FIXES:
- Added locks for buffer access (Issue #1)
- Added locks for serial operations (Issue #3)
- Ensured non-blocking mode to prevent deadlock (Issue #5)
"""

import serial
import time
import threading
from typing import Optional


class SerialTransport:
    """Non-blocking serial transport with auto-reconnect capability and thread-safety"""
    
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 0.0):
        """
        Initialize serial transport.
        
        Args:
            port: Serial port device (e.g., '/dev/ttyAMA0')
            baudrate: Communication speed (default: 115200)
            timeout: Read timeout in seconds (0 = non-blocking - CRITICAL!)
        """
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout  # MUST BE 0.0 for non-blocking!
        self.ser: Optional[serial.Serial] = None
        self.rx_buffer = bytearray()
        self.connected = False
        
        # ✅ SINGLE LOCK for all serial and buffer operations
        self.lock = threading.Lock()
        
        # Connection tracking
        self.reconnect_delay = 2.0  # seconds
        self.last_connect_attempt = 0
        self.connection_errors = 0
        
        # Try initial connection
        self._connect()
    
    def _connect(self) -> bool:
        """
        Attempt to open serial connection.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            # Close existing connection if any
            if self.ser and self.ser.is_open:
                self.ser.close()
            
            # ✅ CRITICAL: timeout=0.0 for non-blocking to prevent deadlock
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,  # Non-blocking!
                write_timeout=1.0
            )
            
            self.connected = True
            self.connection_errors = 0
            return True
            
        except serial.SerialException:
            self.connected = False
            self.connection_errors += 1
            return False
        except Exception:
            self.connected = False
            self.connection_errors += 1
            return False
    
    def _try_reconnect(self) -> bool:
        """
        Attempt reconnection with rate limiting.
        
        Returns:
            True if reconnection successful
        """
        now = time.time()
        
        # Rate limit reconnection attempts
        if now - self.last_connect_attempt < self.reconnect_delay:
            return False
        
        self.last_connect_attempt = now
        return self._connect()
    
    def write(self, data: bytes) -> bool:
        """
        Write data to serial port (THREAD-SAFE).
        
        Args:
            data: Bytes to transmit
            
        Returns:
            True if write successful, False on error
        """
        if not self.connected:
            if not self._try_reconnect():
                return False
        
        try:
            # ✅ LOCK for serial write
            with self.lock:
                if self.ser and self.ser.is_open:
                    self.ser.write(data)
                    return True
                else:
                    self.connected = False
                    return False
                    
        except serial.SerialTimeoutException:
            # Write timeout - not fatal, just warn
            return False
            
        except serial.SerialException:
            self.connected = False
            return False
            
        except Exception:
            self.connected = False
            return False
    
    def poll(self) -> int:
        """
        Read available data from serial port (non-blocking, THREAD-SAFE).
        
        Returns:
            Number of bytes read
        """
        if not self.connected:
            if not self._try_reconnect():
                return 0
        
        try:
            # ✅ LOCK for buffer management and serial read
            with self.lock:
                # Clear buffer if too large
                if len(self.rx_buffer) > 1024:
                    self.rx_buffer.clear()
                
                # Non-blocking read (timeout=0)
                if self.ser and self.ser.is_open:
                    data = self.ser.read(256)
                else:
                    self.connected = False
                    return 0
                
                # Extend buffer while holding lock
                if data:
                    self.rx_buffer.extend(data)
                    return len(data)
            
            return 0
            
        except serial.SerialException:
            with self.lock:
                self.connected = False
            return 0
            
        except Exception:
            with self.lock:
                self.connected = False
            return 0
    
    def get_buffer(self) -> bytearray:
        """
        Get reference to RX buffer (for protocol parsing).
        
        WARNING: Caller must hold self.lock when accessing buffer!
        Better: Use this only from same thread as poll().
        
        Returns:
            Reference to internal RX buffer
        """
        return self.rx_buffer
    
    def is_connected(self) -> bool:
        """
        Check if serial connection is active.
        
        Returns:
            True if connected and healthy
        """
        with self.lock:
            return self.connected and self.ser is not None and self.ser.is_open
    
    def close(self):
        """Close serial port cleanly."""
        try:
            with self.lock:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                self.connected = False
        except:
            pass
    
    def __del__(self):
        """Cleanup on deletion."""
        self.close()
