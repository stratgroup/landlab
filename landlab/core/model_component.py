#! /usr/bin/env python
from __future__ import print_function

import os
import textwrap


_VAR_HELP_MESSAGE = """
name: {name}
description:
{desc}
units: {units}
at: {loc}
"""


class classproperty(property):
    def __get__(self, cls, owner):
        return self.fget.__get__(None, owner)()


class Component(object):
    _input_var_names = set()
    _output_var_names = set()
    _var_units = dict()

    def __init__(self, grid, map_vars=None):
        map_vars = map_vars or {}
        self._grid = grid

        for (location, vars) in map_vars.items():
            for (dest, src) in vars.items():
                grid.add_field(location, dest,
                               grid.field_values(location, src))

    @classproperty
    @classmethod
    def input_var_names(cls):
        """Names of fields that are used by the component.
        
        Returns
        -------
        tuple of str
            Tuple of field names.
        """
        return tuple(cls._input_var_names)

    @classproperty
    @classmethod
    def output_var_names(self):
        """Names of fields that are provided by the component.
        
        Returns
        -------
        tuple of str
            Tuple of field names.
        """
        return tuple(self._output_var_names)

    @classproperty
    @classmethod
    def name(self):
        """Name of the component.

        Returns
        -------
        str
            Component name.
        """
        return self._name

    @classproperty
    @classmethod
    def units(self):
        """Get the units for all field values.

        Returns
        -------
        tuple or str
            Units for each field.
        """
        return tuple(self._var_units.items())

    @classmethod
    def var_units(cls, name):
        """Get the units of a particular field.

        Parameters
        ----------
        name : str
            A field name.

        Returns
        -------
        str
            Units for the given field.
        """
        return cls._var_units[name]

    @classproperty
    @classmethod
    def definitions(cls):
        """Get a description of each field.

        Returns
        -------
        tuple of (*name*, *description*)
            A description of each field.
        """
        return tuple(cls._var_doc.items())

    @classmethod
    def var_definition(cls, name):
        """Get a description of a particular field.

        Parameters
        ----------
        name : str
            A field name.

        Returns
        -------
        tuple of (*name*, *description*)
            A description of each field.
        """
        return cls._var_doc[name]

    @classmethod
    def var_help(cls, name):
        """Print a help message for a particular field.

        Parameters
        ----------
        name : str
            A field name.
        """
        desc = os.linesep.join(textwrap.wrap(cls._var_doc[name],
                                             initial_indent='  ',
                                             subsequent_indent='  '))
        units = cls._var_units[name]
        loc = cls._var_mapping[name]

        help = _VAR_HELP_MESSAGE.format(name=name, desc=desc, units=units,
                                        loc=loc)

        print(help.strip())

    @classproperty
    @classmethod
    def var_mapping(self):
        """Location where variables are defined.

        Returns
        -------
        tuple of (name, location)
            Tuple of variable name and location ('node', 'link', etc.) pairs.
        """
        return tuple(self._var_mapping.items())

    @classmethod
    def var_loc(cls, name):
        """Location where a particular variable is defined.

        Returns
        -------
        str
            The location ('node', 'link', etc.) where a variable is defined.
        """
        return cls._var_mapping[name]

    @property
    def shape(self):
        return self.grid._shape

    @property
    def grid(self):
        return self._grid

    @property
    def coords(self):
        return (self.grid.node_x, self.grid.node_y)

    def imshow(self, name, **kwds):
        self._grid.imshow(name, **kwds)
