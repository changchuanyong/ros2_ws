from glob import glob

from setuptools import find_packages, setup


package_name = "rm_l20_driver"

setup(
    name=package_name,
    version="0.1.0",
    packages=find_packages(exclude=["test"]),
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml", "LICENSE", "THIRD_PARTY.md", "README.md"]),
        ("share/" + package_name + "/launch", glob("launch/*.launch.py")),
    ],
    install_requires=["setuptools", "pymodbus==3.5.1", "pyserial==3.5", "numpy>=1.21,<2"],
    zip_safe=False,
    maintainer="dianjinglab",
    maintainer_email="dianjinglab@todo.todo",
    description="L20 RS485 position commands and feedback for ROS 2 Humble",
    license="Apache-2.0",
    tests_require=["pytest"],
    entry_points={
        "console_scripts": ["l20_rs485_driver = rm_l20_driver.node:main"],
    },
)
