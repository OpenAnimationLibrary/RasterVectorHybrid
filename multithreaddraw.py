import sys
import threading
import os
import configparser
from collections import deque
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QAction, QFileDialog, QGraphicsView, QGraphicsScene,
    QGraphicsItem, QGraphicsPixmapItem, QGraphicsPathItem, QDockWidget, QListWidget,
    QPushButton, QVBoxLayout, QWidget, QInputDialog
)
from PyQt5.QtGui import (
    QPainter, QPen, QPixmap, QPainterPath, QBrush, QTabletEvent, QImage
)
from PyQt5.QtCore import (
    Qt, QPointF, QEvent, QProcess, QRectF, QSize, QFile, QDataStream, QByteArray, QBuffer
)

class DrawingView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.scene = QGraphicsScene()
        self.setScene(self.scene)
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.current_pen_width = 2
        self.pen_color = Qt.black
        self.pen = QPen(self.pen_color, self.current_pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.last_points = deque(maxlen=3)  # Store the last three points for smoothing
        self.drawing = False
        self.vector_path = QPainterPath()
        self.vector_item = QGraphicsPathItem()
        self.vector_item.setPen(self.pen)
        self.scene.addItem(self.vector_item)
        self.raster_pixmap = QPixmap(10000, 10000)
        self.raster_pixmap.fill(Qt.transparent)
        self.raster_item = QGraphicsPixmapItem(self.raster_pixmap)
        self.scene.addItem(self.raster_item)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.scale_factor = 1.0
        self.background_visible = True  # Background is visible by default
        self.background_color = Qt.white  # Default background color

        # Add background rect
        self.background_rect = self.scene.addRect(
            -5000, -5000, 10000, 10000,
            pen=QPen(Qt.NoPen),
            brush=QBrush(self.background_color)
        )
        self.background_rect.setZValue(-1)
        self.background_rect.setAcceptedMouseButtons(Qt.NoButton)  # Prevent it from accepting mouse events

        # Pins
        self.pins = []  # List of pins: {'name': str, 'pos': QPointF}
        self.default_pin = {'name': 'Default Pin', 'pos': QPointF(0, 0)}
        self.pins.append(self.default_pin)

        # Enable tablet events
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.setTabletTracking(True)
        self.use_tablet = False

        # Antialiasing setting
        self.antialiasing_enabled = False  # Default to False

        # Load settings
        self.load_settings()

        # Stroke data for raster drawing
        self.stroke_points = []
        self.stroke_pen_widths = []
        self.raster_bounding_rect = QRectF()  # Initialize raster bounding rect

    def load_settings(self):
        config = configparser.ConfigParser()
        if os.path.exists('rvsettings.ini'):
            config.read('rvsettings.ini')
            # Load pins
            if 'Pins' in config.sections():
                self.pins = []
                for name in config['Pins']:
                    pos_str = config['Pins'][name]
                    x_str, y_str = pos_str.split(',')
                    x = float(x_str)
                    y = float(y_str)
                    self.pins.append({'name': name, 'pos': QPointF(x, y)})
            # Load view center
            if 'View' in config.sections():
                x = float(config['View'].get('center_x', '0'))
                y = float(config['View'].get('center_y', '0'))
                self.centerOn(QPointF(x, y))
            # Load background visibility
            if 'Settings' in config.sections():
                bg_visible = config['Settings'].getboolean('background_visible', True)
                self.background_visible = bg_visible
                self.background_color = Qt.white if bg_visible else Qt.transparent
                self.background_rect.setBrush(QBrush(self.background_color))
                self.update()
                # Load antialiasing setting
                self.antialiasing_enabled = config['Settings'].getboolean('antialiasing', False)

    def save_settings(self):
        config = configparser.ConfigParser()
        # Save pins
        config['Pins'] = {}
        for pin in self.pins:
            x = pin['pos'].x()
            y = pin['pos'].y()
            config['Pins'][pin['name']] = f'{x},{y}'
        # Save view center
        center = self.mapToScene(self.viewport().rect().center())
        config['View'] = {
            'center_x': str(center.x()),
            'center_y': str(center.y())
        }
        # Save background visibility and antialiasing setting
        config['Settings'] = {
            'background_visible': str(self.background_visible),
            'antialiasing': str(self.antialiasing_enabled)
        }
        with open('rvsettings.ini', 'w') as configfile:
            config.write(configfile)

    def closeEvent(self, event):
        self.save_settings()
        super().closeEvent(event)

    def toggle_background(self):
        if self.background_visible:
            self.background_color = Qt.transparent
            self.background_rect.setBrush(QBrush(self.background_color))
            self.background_visible = False
        else:
            self.background_color = Qt.white
            self.background_rect.setBrush(QBrush(self.background_color))
            self.background_visible = True
        self.update()

    def update_pen(self):
        self.pen = QPen(self.pen_color, self.current_pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        self.vector_item.setPen(self.pen)

    def smooth_path(self, new_point):
        self.last_points.append(new_point)
        if len(self.last_points) == 3:
            p0, p1, p2 = self.last_points
            # Calculate the control point for quadratic Bezier curve
            cpx = p1.x()
            cpy = p1.y()
            self.vector_path.quadTo(QPointF(cpx, cpy), p2)
            self.vector_item.setPath(self.vector_path)

    def tabletEvent(self, event):
        self.use_tablet = True
        if event.type() == QEvent.TabletPress:
            self.last_points.clear()
            self.stroke_points.clear()
            self.stroke_pen_widths.clear()
            self.drawing = True
            point = event.posF()
            self.last_points.append(point)
            self.vector_path.moveTo(point)
            self.stroke_points.append(point)
            pressure = event.pressure()
            self.current_pen_width = max(1, pressure * 10)
            self.stroke_pen_widths.append(self.current_pen_width)
            self.update_pen()
            event.accept()
        elif event.type() == QEvent.TabletMove and self.drawing:
            point = event.posF()
            pressure = event.pressure()
            self.current_pen_width = max(1, pressure * 10)
            self.stroke_pen_widths.append(self.current_pen_width)
            self.update_pen()
            self.smooth_path(point)
            self.stroke_points.append(point)
            event.accept()
        elif event.type() == QEvent.TabletRelease:
            if self.drawing:
                self.process_raster_stroke()
            self.drawing = False
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        if not self.use_tablet and event.button() == Qt.LeftButton:
            self.last_points.clear()
            self.stroke_points.clear()
            self.stroke_pen_widths.clear()
            self.drawing = True
            point = self.mapToScene(event.pos())
            self.last_points.append(point)
            self.vector_path.moveTo(point)
            self.stroke_points.append(point)
            self.update_pen()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.use_tablet and self.drawing:
            point = self.mapToScene(event.pos())
            self.update_pen()
            self.smooth_path(point)
            self.stroke_points.append(point)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if not self.use_tablet and event.button() == Qt.LeftButton and self.drawing:
            if self.drawing:
                self.process_raster_stroke()
            self.drawing = False
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def process_raster_stroke(self):
        # Draw the stroke on the raster_pixmap
        painter = QPainter(self.raster_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.moveTo(self.stroke_points[0])
        for i in range(1, len(self.stroke_points)):
            p0 = self.stroke_points[i - 1]
            p1 = self.stroke_points[i]
            cp = QPointF((p0.x() + p1.x()) / 2, (p0.y() + p1.y()) / 2)
            path.quadTo(cp, p1)
        pen = QPen(self.pen_color, self.current_pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()
        self.raster_item.setPixmap(self.raster_pixmap)

        # Update raster bounding rect
        stroke_bounding_rect = path.boundingRect()
        if self.raster_bounding_rect.isNull():
            self.raster_bounding_rect = stroke_bounding_rect
        else:
            self.raster_bounding_rect = self.raster_bounding_rect.united(stroke_bounding_rect)

    def wheelEvent(self, event):
        if event.modifiers() == Qt.ControlModifier:
            angle = event.angleDelta().y()
            factor = 1.25 if angle > 0 else 0.8
            self.scale(factor, factor)
            self.scale_factor *= factor
            event.accept()
        else:
            super().wheelEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Plus:
            self.scale(1.25, 1.25)
            self.scale_factor *= 1.25
        elif event.key() == Qt.Key_Minus:
            self.scale(0.8, 0.8)
            self.scale_factor *= 0.8
        else:
            super().keyPressEvent(event)

    def clear_canvas(self):
        self.vector_path = QPainterPath()
        self.vector_item.setPath(self.vector_path)
        self.raster_pixmap.fill(Qt.transparent)
        self.raster_item.setPixmap(self.raster_pixmap)
        self.raster_bounding_rect = QRectF()  # Reset raster bounding rect

    def save_raster_image(self, file_path):
        # Compute the bounding rectangle of the drawn content
        vector_bounding_rect = self.vector_path.boundingRect()
        raster_bounding_rect = self.raster_bounding_rect

        total_bounding_rect = vector_bounding_rect.united(raster_bounding_rect)

        if total_bounding_rect.isNull() or total_bounding_rect.isEmpty():
            # Nothing to save
            return

        # Adjust to integer rectangle
        total_bounding_rect = total_bounding_rect.toAlignedRect()

        # Create a pixmap of the bounding rectangle size
        width = total_bounding_rect.width()
        height = total_bounding_rect.height()
        temp_pixmap = QPixmap(width, height)
        temp_pixmap.fill(self.background_color)

        # Paint the raster and vector onto the pixmap
        painter = QPainter(temp_pixmap)
        if self.antialiasing_enabled:
            painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(-total_bounding_rect.topLeft())

        # Draw raster
        painter.drawPixmap(0, 0, self.raster_pixmap.copy(total_bounding_rect))

        # Draw vector
        painter.setPen(self.pen)
        painter.drawPath(self.vector_path)

        painter.end()

        # Binarize the image
        image = temp_pixmap.toImage()

        for y in range(image.height()):
            for x in range(image.width()):
                color = image.pixelColor(x, y)
                # Calculate the brightness
                brightness = (color.red() + color.green() + color.blue()) / 3
                if brightness < 128:
                    image.setPixelColor(x, y, Qt.black)
                else:
                    image.setPixelColor(x, y, Qt.white)

        # Convert back to pixmap
        temp_pixmap = QPixmap.fromImage(image)

        temp_pixmap.save(file_path, 'PNG')

    def save_vector_data(self, file_path):
        from PyQt5.QtSvg import QSvgGenerator

        # Compute the bounding rectangle of the drawn content
        vector_bounding_rect = self.vector_path.boundingRect()
        raster_bounding_rect = self.raster_bounding_rect

        total_bounding_rect = vector_bounding_rect.united(raster_bounding_rect)

        if total_bounding_rect.isNull() or total_bounding_rect.isEmpty():
            # Nothing to save
            return

        # Adjust to rectangle
        total_bounding_rect = total_bounding_rect.toRect()

        # Get the minimum x and y to adjust coordinates
        min_x = total_bounding_rect.left()
        min_y = total_bounding_rect.top()
        width = total_bounding_rect.width()
        height = total_bounding_rect.height()

        generator = QSvgGenerator()
        generator.setFileName(file_path)
        generator.setSize(QSize(width, height))
        generator.setViewBox(QRectF(0, 0, width, height))
        generator.setTitle("Vector Drawing")
        generator.setDescription("An SVG drawing created by PyQt")

        painter = QPainter(generator)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.translate(-min_x, -min_y)  # Shift the drawing to (0,0)
        pen = QPen(self.pen_color, self.current_pen_width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(self.vector_path)
        painter.end()

    # Pins functionality
    def add_pin(self, name, pos):
        pin = {'name': name, 'pos': pos}
        self.pins.append(pin)

    def remove_pin(self, name):
        self.pins = [pin for pin in self.pins if pin['name'] != name]

    def get_pins(self):
        return self.pins

    # Save and load canvas
    def save_canvas_to_file(self, file_path):
        file = QFile(file_path)
        if not file.open(QFile.WriteOnly):
            return False
        stream = QDataStream(file)

        # Save raster_pixmap
        raster_bytes = QByteArray()
        buffer = QBuffer(raster_bytes)
        buffer.open(QBuffer.WriteOnly)
        self.raster_pixmap.save(buffer, 'PNG')
        stream.writeUInt32(raster_bytes.size())
        stream.writeBytes(raster_bytes.data())

        # Save vector_path
        elements = []
        for i in range(self.vector_path.elementCount()):
            elem = self.vector_path.elementAt(i)
            elements.append((elem.type, elem.x, elem.y))
        stream.writeUInt32(len(elements))
        for elem_type, x, y in elements:
            stream.writeUInt8(elem_type)
            stream.writeDouble(x)
            stream.writeDouble(y)

        # Save pins
        stream.writeUInt32(len(self.pins))
        for pin in self.pins:
            name_bytes = pin['name'].encode('utf-8')
            stream.writeUInt32(len(name_bytes))
            stream.writeRawData(name_bytes)
            stream.writeDouble(pin['pos'].x())
            stream.writeDouble(pin['pos'].y())

        # Save background visibility
        stream.writeBool(self.background_visible)

        file.close()
        return True

    def load_canvas_from_file(self, file_path):
        file = QFile(file_path)
        if not file.open(QFile.ReadOnly):
            return False
        stream = QDataStream(file)

        # Load raster_pixmap
        raster_size = stream.readUInt32()
        raster_data = stream.readBytes()
        raster_bytes = QByteArray(raster_data)
        raster_image = QImage()
        raster_image.loadFromData(raster_bytes, 'PNG')
        self.raster_pixmap = QPixmap.fromImage(raster_image)
        self.raster_item.setPixmap(self.raster_pixmap)
        self.raster_bounding_rect = QRectF(self.raster_pixmap.rect())  # Ensure QRectF

        # Load vector_path
        element_count = stream.readUInt32()
        elements = []
        for _ in range(element_count):
            elem_type = stream.readUInt8()
            x = stream.readDouble()
            y = stream.readDouble()
            elements.append((elem_type, x, y))
        self.vector_path = QPainterPath()
        i = 0
        while i < len(elements):
            elem_type, x, y = elements[i]
            if elem_type == 0:  # MoveToElement
                self.vector_path.moveTo(x, y)
                i += 1
            elif elem_type == 1:  # LineToElement
                self.vector_path.lineTo(x, y)
                i += 1
            elif elem_type == 2:  # CurveToElement
                if i + 2 < len(elements):
                    ctrl1_x = x
                    ctrl1_y = y
                    i += 1
                    _, ctrl2_x, ctrl2_y = elements[i]
                    i += 1
                    _, end_x, end_y = elements[i]
                    self.vector_path.cubicTo(ctrl1_x, ctrl1_y, ctrl2_x, ctrl2_y, end_x, end_y)
                    i += 1
                else:
                    break  # Not enough data for a curve
            else:
                i += 1  # Unknown element type
        self.vector_item.setPath(self.vector_path)

        # Load pins
        pin_count = stream.readUInt32()
        self.pins = []
        for _ in range(pin_count):
            name_length = stream.readUInt32()
            name_bytes = stream.readRawData(name_length)
            name = name_bytes.decode('utf-8')
            x = stream.readDouble()
            y = stream.readDouble()
            self.pins.append({'name': name, 'pos': QPointF(x, y)})

        # Load background visibility
        self.background_visible = stream.readBool()
        self.background_color = Qt.white if self.background_visible else Qt.transparent
        self.background_rect.setBrush(QBrush(self.background_color))
        self.update()

        file.close()
        return True

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Hybrid Drawing App with Infinite Canvas and Pins")
        self.view = DrawingView()
        self.setCentralWidget(self.view)
        self.create_menu()
        self.create_pins_panel()
        self.update_pins_list()

    def create_menu(self):
        main_menu = self.menuBar()
        file_menu = main_menu.addMenu('File')

        save_canvas_action = QAction('Save Canvas', self)
        save_canvas_action.triggered.connect(self.save_canvas)
        file_menu.addAction(save_canvas_action)

        open_canvas_action = QAction('Open Canvas', self)
        open_canvas_action.triggered.connect(self.open_canvas)
        file_menu.addAction(open_canvas_action)

        save_raster_action = QAction('Save Raster Image', self)
        save_raster_action.triggered.connect(self.save_raster_image)
        file_menu.addAction(save_raster_action)

        save_vector_action = QAction('Save Vector Data', self)
        save_vector_action.triggered.connect(self.save_vector_data)
        file_menu.addAction(save_vector_action)

        save_multi_action = QAction('Save Multi (Raster/Vector)', self)
        save_multi_action.triggered.connect(self.save_multi)
        file_menu.addAction(save_multi_action)

        restart_action = QAction('Restart', self)
        restart_action.triggered.connect(self.restart_application)
        file_menu.addAction(restart_action)

        clear_action = QAction('Clear Canvas', self)
        clear_action.triggered.connect(self.clear_canvas)
        file_menu.addAction(clear_action)

        view_menu = main_menu.addMenu('View')
        toggle_bg_action = QAction('Toggle Background', self)
        toggle_bg_action.setCheckable(True)
        toggle_bg_action.setChecked(self.view.background_visible)
        toggle_bg_action.triggered.connect(self.toggle_background)
        view_menu.addAction(toggle_bg_action)

    def toggle_background(self):
        self.view.toggle_background()

    def save_canvas(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Canvas", "", "Canvas Files (*.canvas)")
        if file_path:
            self.view.save_canvas_to_file(file_path)

    def open_canvas(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Canvas", "", "Canvas Files (*.canvas)")
        if file_path:
            self.view.load_canvas_from_file(file_path)
            self.update_pins_list()

    def save_raster_image(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Raster Image", "", "PNG Files (*.png)")
        if file_path:
            self.view.save_raster_image(file_path)

    def save_vector_data(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Vector Data", "", "SVG Files (*.svg)")
        if file_path:
            self.view.save_vector_data(file_path)

    def save_multi(self):
        base_name = 'imagemulti.'
        num = 1
        while True:
            raster_filename = f"{base_name}{num:04d}.png"
            vector_filename = f"{base_name}{num:04d}.svg"
            if not os.path.exists(raster_filename) and not os.path.exists(vector_filename):
                break
            num += 1
        self.view.save_raster_image(raster_filename)
        self.view.save_vector_data(vector_filename)

    def restart_application(self):
        self.view.save_settings()
        QApplication.quit()
        QProcess.startDetached(sys.executable, sys.argv)

    def closeEvent(self, event):
        self.view.save_settings()
        super().closeEvent(event)

    def clear_canvas(self):
        self.view.clear_canvas()

    def create_pins_panel(self):
        self.pins_dock = QDockWidget("Pins", self)
        self.addDockWidget(Qt.RightDockWidgetArea, self.pins_dock)

        self.pins_list_widget = QListWidget()
        self.pins_list_widget.installEventFilter(self)  # Install event filter to capture key events
        self.update_pins_list()

        add_pin_button = QPushButton("Add Pin")
        add_pin_button.clicked.connect(self.add_pin)

        layout = QVBoxLayout()
        layout.addWidget(self.pins_list_widget)
        layout.addWidget(add_pin_button)

        container = QWidget()
        container.setLayout(layout)
        self.pins_dock.setWidget(container)

    def eventFilter(self, source, event):
        if source == self.pins_list_widget and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Delete:
                self.delete_selected_pin()
                return True
        return super().eventFilter(source, event)

    def update_pins_list(self):
        self.pins_list_widget.clear()
        for pin in self.view.get_pins():
            self.pins_list_widget.addItem(pin['name'])
        self.pins_list_widget.itemDoubleClicked.connect(self.pin_selected)

    def add_pin(self):
        name, ok = QInputDialog.getText(self, "Add Pin", "Enter pin name:")
        if ok and name:
            pos = self.view.mapToScene(self.view.viewport().rect().center())
            self.view.add_pin(name, pos)
            self.update_pins_list()

    def delete_selected_pin(self):
        selected_items = self.pins_list_widget.selectedItems()
        if not selected_items:
            return
        for item in selected_items:
            pin_name = item.text()
            self.view.remove_pin(pin_name)
            self.pins_list_widget.takeItem(self.pins_list_widget.row(item))

    def pin_selected(self, item):
        pin_name = item.text()
        for pin in self.view.get_pins():
            if pin['name'] == pin_name:
                self.view.centerOn(pin['pos'])
                break

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
