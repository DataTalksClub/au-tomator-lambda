import re


def handle_qoutes(template, placeholder_values):
    def quote_replacement(match):
        placeholder = match.group(1).strip()

        if placeholder not in placeholder_values:
            return match.group(0)

        value = placeholder_values[placeholder].strip()
        lines = value.split('\n')

        # don't do anything if it's not multi-line
        if len(lines) == 1:
            return match.group(0)

        quoted_lines = [f'>{line}\n' for line in lines]
        return ''.join(quoted_lines)

    quote_pattern = r'^>\s*\{([^}]+)\}\s*$'

    result = re.sub(
        quote_pattern,
        quote_replacement,
        template,
        flags=re.MULTILINE
    )

    return result


def prepare_values(placeholders, channel_name):
    placeholder_values = {}

    for key, value in placeholders.items():
        if isinstance(value, dict):
            if channel_name in value:
                placeholder_value = value[channel_name]
            elif 'default' in value:
                placeholder_value = value['default']
            else:
                # no default value, don't do anything for this channel
                return None
        else:
            placeholder_value = value

        placeholder_values[key] = placeholder_value

    return placeholder_values


def format_message(message_template, placeholders, channel_name):
    placeholder_values = prepare_values(placeholders, channel_name)
    if placeholder_values is None:
        return None

    message = handle_qoutes(message_template, placeholder_values)
    message = message.format(**placeholder_values)

    return message